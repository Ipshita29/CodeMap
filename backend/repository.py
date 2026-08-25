"""repository.py -- everything about accessing and understanding the
repository itself: cloning, the canonical file/folder scan, language and
tech-stack detection, the repository tree, and Git metadata (history,
activity, contributors).

This is CodeMap's ONE source of truth for "what does this repository
actually contain". analyzer.py and ai.py build on top of the
`AnalysisResult` / `GitSummaryResponse` this module produces -- neither
re-derives file counts, folder counts, languages, or contributors on its
own. Concretely:

  Repository (on disk, cloned by GitService)
        |
        v
  RepositoryAnalyzer.analyze() -> AnalysisResult   <- get_repository_snapshot() stamps this
        |                                             with repository_version() (the current
        v                                             commit SHA, or a mtime fallback for a
  files / folders / languages / repository_tree       non-Git directory) and caches it per
        |                                             (path, version), so every caller in one
        v                                             request cycle -- and ai.py's answer
  GitAnalyzer                  -> commit history /    cache -- reads the identical scan and
                                   activity /          agree on what "the same repository"
                                   contributors         means, instead of each re-deriving it.

repository_version() is the ONE place "what version of this repository is
this" gets decided. Nothing else in this file, analyzer.py, or ai.py
computes its own notion of repository identity/version.

Sections in this file:
  1. Constants (ignored dirs, binary extensions, language table)
  2. Lightweight per-file import extraction (used during the scan itself)
  3. File scanning
  4. Canonical file+folder tree
  5. Tech stack / framework detection
  6. Canonical repository snapshot (RepositoryAnalyzer + AnalysisResult)
  7. Repository version identity + cached snapshot accessor
  8. Repository cloning
  9. Git history / activity / contributors
  10. Pydantic response models (import/analysis/tree/git)
  11. Git service-layer functions
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from pydantic import BaseModel

from config import settings
from utils import NoRepositoryImportedError, RepositoryAnalysisError, RepositoryCloneError

logger = logging.getLogger(__name__)


# =====================================================================
# 1. Constants -- shared, framework-agnostic lookup tables.
# =====================================================================

# Directories that add noise (dependencies, build output, VCS internals) and
# should never be walked into. Checked by directory *name*, at any depth.
IGNORED_DIRS: set[str] = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "coverage",
}

# Extensions we don't attempt to read as text (line counts and import
# extraction are meaningless for these; size is still recorded).
BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".flac", ".wav", ".ogg",
    ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".wasm",
    ".pyc", ".pyo",
    # 3D / design assets
    ".glb", ".gltf", ".obj", ".fbx", ".stl", ".blend", ".3ds",
    ".psd", ".ai", ".sketch", ".heic",
    # Data / ML artifacts -- text-decodable in the sense that Python won't
    # raise, but the "lines" they decode to are meaningless noise.
    ".pkl", ".pickle", ".db", ".sqlite", ".sqlite3", ".parquet",
    ".h5", ".hdf5", ".onnx", ".pt", ".pth", ".npy", ".npz", ".model", ".bin", ".dat",
}

# Extension -> human-readable language name, used for both the per-file
# `language` field and the repository-wide language breakdown. Extensions
# absent from this map are reported as "Other" and excluded from language
# counts (keeps the breakdown meaningful instead of dumping every stray
# extension into it).
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".xml": "XML",
    ".toml": "TOML",
}


# =====================================================================
# 2. Lightweight per-file import extraction, used during the scan itself
#    (not to be confused with analyzer.py's full Tree-sitter parsing --
#    this is a cheap regex pass so FileScanner can populate FileRecord
#    .imports without waiting for Day 3 code intelligence).
# =====================================================================

JS_IMPORT_EXTENSIONS: set[str] = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"}
PYTHON_IMPORT_EXTENSIONS: set[str] = {".py"}

# Matches `import X from "Y"`, `import "Y"`, `export ... from "Y"`, and
# `require("Y")`. Deliberately regex-based rather than AST/Tree-sitter based
# — good enough to seed a future dependency graph, not a correctness-critical
# parser.
_JS_IMPORT_PATTERN = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\sfrom\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)

_PY_FROM_IMPORT_PATTERN = re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.MULTILINE)
_PY_IMPORT_PATTERN = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)


class ImportExtractor:
    """Best-effort import extraction for JS/TS and Python source text.

    Stores the *source* being imported from (module path / package name),
    not the local binding name — e.g. `import Navbar from "./Navbar"` yields
    "./Navbar", and `from fastapi import FastAPI` yields "fastapi". That's
    the shape a future dependency graph needs.
    """

    @classmethod
    def extract(cls, content: str, extension: str) -> list[str]:
        if extension in JS_IMPORT_EXTENSIONS:
            return cls._extract_js(content)
        if extension in PYTHON_IMPORT_EXTENSIONS:
            return cls._extract_python(content)
        return []

    @staticmethod
    def _extract_js(content: str) -> list[str]:
        imports: list[str] = []
        for match in _JS_IMPORT_PATTERN.finditer(content):
            source = match.group(1) or match.group(2)
            if source:
                imports.append(source)
        return imports

    @staticmethod
    def _extract_python(content: str) -> list[str]:
        imports: list[str] = []
        for match in _PY_FROM_IMPORT_PATTERN.finditer(content):
            imports.append(match.group(1))
        for match in _PY_IMPORT_PATTERN.finditer(content):
            imports.extend(name.strip() for name in match.group(1).split(","))
        return imports


# =====================================================================
# 3. File scanning
# =====================================================================


@dataclass
class FileRecord:
    path: str
    extension: str
    language: str
    size_bytes: int
    lines: int
    imports: list[str] = field(default_factory=list)


class FileScanner:
    """Recursively scans a repository and extracts per-file metadata.

    Walks with `os.walk` and prunes ignored directory names *before*
    descending into them, so a huge `node_modules` or `.git` tree is never
    actually traversed — this is what keeps the scan cheap on real repos.
    """

    def __init__(self, root: Path):
        self.root = root

    def scan(self) -> list[FileRecord]:
        records: list[FileRecord] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
            for filename in filenames:
                records.append(self._build_record(Path(dirpath) / filename))
        return records

    def _build_record(self, path: Path) -> FileRecord:
        relative = path.relative_to(self.root).as_posix()
        extension = path.suffix
        language = LANGUAGE_EXTENSIONS.get(extension, "Other")
        size_bytes = self._safe_size(path)

        content = None if extension in BINARY_EXTENSIONS else self._read_text(path)
        lines = len(content.splitlines()) if content else 0
        imports = ImportExtractor.extract(content, extension) if content else []

        return FileRecord(
            path=relative,
            extension=extension,
            language=language,
            size_bytes=size_bytes,
            lines=lines,
            imports=imports,
        )

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None


# =====================================================================
# 4. Canonical file+folder tree -- the one tree every tree-based UI (the
#    Architecture Repository Map, the AI context's folder summary, ...)
#    reads from.
#
#    Built from the *file paths FileScanner already discovered* rather than
#    a second `os.walk`/`iterdir` pass over disk: every file that
#    contributes to total_files/languages/line counts also contributes its
#    directory chain here, which is what makes total_folders (the count of
#    directory nodes produced below) provably consistent with the tree
#    instead of two independently-computed numbers that can drift apart. A
#    directory that owns zero files can't exist in a git-cloned repository
#    anyway (git doesn't track empty directories), so this loses nothing
#    real.
# =====================================================================


@dataclass
class TreeNode:
    name: str
    type: str  # "file" | "directory"
    path: str
    children: list["TreeNode"] | None = field(default=None)

    def to_dict(self) -> dict:
        data: dict = {"name": self.name, "type": self.type, "path": self.path}
        if self.children is not None:
            data["children"] = [child.to_dict() for child in self.children]
        return data


def build_repository_tree(file_paths: list[str]) -> tuple[list[TreeNode], int]:
    """Returns (root-level nodes, directory_count).

    `directory_count` is every directory node in the tree, at any depth --
    the repository root itself is never counted (root isn't a folder
    *within* the repository, it IS the repository), matching the existing
    "total_folders excludes root" definition.
    """
    root: dict = {}

    for relative_path in file_paths:
        parts = relative_path.split("/")
        cursor = root
        for index, part in enumerate(parts):
            is_terminal = index == len(parts) - 1
            node_path = "/".join(parts[: index + 1])
            if part not in cursor:
                cursor[part] = {
                    "name": part,
                    "path": node_path,
                    "is_file": is_terminal,
                    "children": {},
                }
            entry = cursor[part]
            if is_terminal:
                # A real filesystem path can't be both a file and a directory,
                # so the terminal segment always wins as "file" -- this only
                # matters if scanned paths were ever malformed/duplicated.
                entry["is_file"] = True
            cursor = entry["children"]

    directory_count = 0

    def _finalize(level: dict) -> list[TreeNode]:
        nonlocal directory_count
        nodes: list[TreeNode] = []
        for entry in level.values():
            if entry["is_file"]:
                nodes.append(TreeNode(name=entry["name"], type="file", path=entry["path"]))
            else:
                directory_count += 1
                nodes.append(
                    TreeNode(
                        name=entry["name"],
                        type="directory",
                        path=entry["path"],
                        children=_finalize(entry["children"]),
                    )
                )
        nodes.sort(key=lambda node: (node.type != "directory", node.name.lower()))
        return nodes

    return _finalize(root), directory_count


# =====================================================================
# 5. Tech stack / framework detection -- evidence-based, from real
#    manifest files the scan already found. Never inferred from the
#    repository name or filenames alone.
# =====================================================================

# Dependency name (as it appears in package.json) -> display name.
PACKAGE_JSON_FRAMEWORKS: dict[str, str] = {
    "react": "React",
    "react-dom": "React",
    "next": "Next.js",
    "express": "Express",
    "vite": "Vite",
    "socket.io": "Socket.IO",
    "socket.io-client": "Socket.IO",
    "axios": "Axios",
    "mongoose": "Mongoose",
    "vue": "Vue.js",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "@nestjs/core": "NestJS",
    "tailwindcss": "Tailwind CSS",
    "@tanstack/react-query": "React Query",
}

# Package name (as it appears in requirements.txt/pyproject.toml, lowercased) -> display name.
REQUIREMENTS_TXT_FRAMEWORKS: dict[str, str] = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "gitpython": "GitPython",
    "uvicorn": "Uvicorn",
}

# Manifest filename -> technology it signals just by existing.
OTHER_MANIFESTS: dict[str, str] = {
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "composer.json": "PHP (Composer)",
    "pom.xml": "Java (Maven)",
    "pubspec.yaml": "Dart/Flutter",
}


class TechStackDetector:
    """Detects frameworks/technologies from manifest files.

    Takes the file list FileScanner already produced instead of walking the
    disk again — one traversal total, and it naturally supports monorepos
    (multiple package.json/requirements.txt at different depths) since it
    just filters by filename rather than assuming a fixed root layout.
    """

    def __init__(self, root: Path, scanned_paths: list[str]):
        self.root = root
        self.scanned_paths = scanned_paths

    def detect(self) -> list[str]:
        frameworks: set[str] = set()
        for relative_path in self.scanned_paths:
            filename = Path(relative_path).name
            if filename == "package.json":
                frameworks |= self._parse_package_json(relative_path)
            elif filename == "requirements.txt":
                frameworks |= self._parse_requirements_txt(relative_path)
            elif filename == "pyproject.toml":
                frameworks |= self._parse_pyproject_toml(relative_path)
            elif filename in OTHER_MANIFESTS:
                frameworks.add(OTHER_MANIFESTS[filename])
        return sorted(frameworks)

    def _parse_package_json(self, relative_path: str) -> set[str]:
        try:
            data = json.loads((self.root / relative_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()

        dependencies = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        return {
            display_name
            for package_name, display_name in PACKAGE_JSON_FRAMEWORKS.items()
            if package_name in dependencies
        }

    def _parse_requirements_txt(self, relative_path: str) -> set[str]:
        try:
            lines = (self.root / relative_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return set()

        return self._match_python_requirement_strings(lines)

    def _parse_pyproject_toml(self, relative_path: str) -> set[str]:
        """PEP 621 (`[project.dependencies]` / `[project.optional-dependencies]`)
        and Poetry (`[tool.poetry.dependencies]`) are both dependency
        manifests just as real as requirements.txt -- most modern Python
        projects declare dependencies here instead, so skipping this file
        would silently miss their actual tech stack evidence."""
        try:
            data = tomllib.loads((self.root / relative_path).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return set()

        requirement_strings: list[str] = list(data.get("project", {}).get("dependencies", []))
        for extra_dependencies in data.get("project", {}).get("optional-dependencies", {}).values():
            requirement_strings.extend(extra_dependencies)

        poetry_dependencies = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        requirement_strings.extend(poetry_dependencies.keys())

        return self._match_python_requirement_strings(requirement_strings)

    @staticmethod
    def _match_python_requirement_strings(requirement_strings: list[str]) -> set[str]:
        detected: set[str] = set()
        for requirement in requirement_strings:
            package_name = re.split(r"[=<>!~\[; ]", requirement.strip().lower())[0]
            if package_name in REQUIREMENTS_TXT_FRAMEWORKS:
                detected.add(REQUIREMENTS_TXT_FRAMEWORKS[package_name])
        return detected


# =====================================================================
# 6. Canonical repository snapshot -- RepositoryAnalyzer scans a cloned
#    repository once and produces the AnalysisResult every other feature
#    (chat, summaries, architecture diagrams, dependency graphs, health
#    scoring) reads from. No AI/LLM involved.
# =====================================================================


@dataclass
class AnalysisResult:
    repository_name: str
    total_files: int
    total_folders: int
    languages: dict[str, int]
    frameworks: list[str]
    repository_tree: list[TreeNode]
    statistics: dict
    files: list[dict]
    # The repository's version identity at scan time (see repository_version()
    # below) -- "" until get_repository_snapshot() stamps it; a bare
    # RepositoryAnalyzer().analyze() call (as several unit tests make
    # directly, with no Git repo present) never needs it.
    repository_version: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["repository_tree"] = [node.to_dict() for node in self.repository_tree]
        return data


class RepositoryAnalyzer:
    """Scans a cloned repository and produces structured, deterministic metadata."""

    def __init__(self, repository_path: Path):
        self.repository_path = Path(repository_path)
        if not self.repository_path.is_dir():
            raise RepositoryAnalysisError(f"Repository path does not exist: {repository_path}")

    def analyze(self) -> AnalysisResult:
        try:
            file_records = FileScanner(self.repository_path).scan()
        except OSError as exc:
            raise RepositoryAnalysisError(f"Failed to scan repository: {exc}") from exc

        file_paths = [record.path for record in file_records]
        repository_tree, total_folders = build_repository_tree(file_paths)
        frameworks = TechStackDetector(self.repository_path, file_paths).detect()

        return AnalysisResult(
            repository_name=self.repository_path.name,
            total_files=len(file_records),
            total_folders=total_folders,
            languages=self._count_languages(file_records),
            frameworks=frameworks,
            repository_tree=repository_tree,
            statistics=self._build_statistics(file_records),
            files=[asdict(record) for record in file_records],
        )

    @staticmethod
    def _count_languages(records: list[FileRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            if record.language == "Other":
                continue
            counts[record.language] = counts.get(record.language, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))

    @staticmethod
    def _build_statistics(records: list[FileRecord]) -> dict:
        total_lines = sum(record.lines for record in records)
        largest_file = max(records, key=lambda record: record.size_bytes, default=None)

        return {
            "total_lines": total_lines,
            "largest_file": (
                {
                    "path": largest_file.path,
                    "size_bytes": largest_file.size_bytes,
                    "lines": largest_file.lines,
                }
                if largest_file
                else None
            ),
        }


# =====================================================================
# 7. Repository version identity + cached snapshot accessor
#
#    repository_version() is the single canonical answer to "what version
#    of this repository is this", reused by both the snapshot cache below
#    and ai.py's answer cache -- so a repository re-import that lands back
#    on the same commit is recognized as the SAME version everywhere (no
#    unnecessary re-analysis, no unnecessarily-invalidated Ask CodeMap
#    history), while any real content change -- a new commit -- is always
#    recognized as a different one.
#
#    get_repository_snapshot() is what every endpoint needing Day 2
#    filesystem-derived facts calls instead of independently re-walking the
#    repository filesystem; it's cached per repository path and keyed on
#    repository_version().
# =====================================================================


def repository_version(repository_path: Path) -> str:
    """The repository's current version identity: the commit SHA when the
    directory is a Git repository -- the reliable signal, since it only
    changes when the checked-out commit itself does -- falling back to the
    directory's own mtime otherwise (a non-Git directory, which a cloned
    repository never is in practice, but this keeps the function total for
    the unit tests that scan a plain tmp_path with no `.git`)."""
    repository_path = Path(repository_path)
    latest_commit = GitAnalyzer(repository_path).latest_commit()
    if latest_commit is not None:
        return latest_commit.hash
    return f"mtime:{repository_path.stat().st_mtime}"


_snapshot_cache: dict[Path, tuple[str, AnalysisResult]] = {}


def get_repository_snapshot(repository_path: Path) -> AnalysisResult:
    repository_path = Path(repository_path)
    version = repository_version(repository_path)

    cached = _snapshot_cache.get(repository_path)
    if cached is not None and cached[0] == version:
        return cached[1]

    result = replace(RepositoryAnalyzer(repository_path).analyze(), repository_version=version)
    _snapshot_cache[repository_path] = (version, result)
    return result


# =====================================================================
# 8. Repository cloning
# =====================================================================


class GitService:
    """Handles cloning GitHub repositories to local disk."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = (base_dir or settings.cloned_repos_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def clone_repository(self, github_url: str, repo_name: str) -> Path:
        """Clone a repository into base_dir/repo_name, replacing it if it already exists."""
        target_path = (self.base_dir / repo_name).resolve()

        # Defense in depth: repo_name is already validated upstream, but never
        # touch a path outside base_dir.
        if self.base_dir not in target_path.parents:
            raise RepositoryCloneError(f"Resolved clone path is unsafe: {target_path}")

        if target_path.exists():
            shutil.rmtree(target_path)

        try:
            Repo.clone_from(github_url, target_path)
        except GitCommandError as exc:
            shutil.rmtree(target_path, ignore_errors=True)
            # Log the full git output (may include local paths) server-side only;
            # the client gets a clean message with no filesystem details.
            logger.warning("git clone failed for %s: %s", github_url, exc)
            raise RepositoryCloneError(
                "Could not clone repository. Check that the URL is correct "
                "and the repository is public."
            ) from exc

        return target_path

    def get_repository_path(self, repository_id: str) -> Path:
        """Resolves an explicit repository_id -- the `repository_name` a
        client already received from POST /repository/import -- to its
        cloned path on disk.

        This is the ONLY way any route identifies "which repository" a
        request is about. It deliberately replaces an earlier
        get_latest_cloned_repository() that picked "whichever directory has
        the newest mtime" -- convenient for a single local user, but wrong
        under any concurrent use: two imports in flight at once meant one
        client's repository could resolve to a different client's data.
        Every route now requires the caller to say explicitly which
        repository it means.
        """
        candidate = (self.base_dir / repository_id).resolve()
        if self.base_dir not in candidate.parents or not candidate.is_dir():
            raise NoRepositoryImportedError(
                f"No imported repository found for '{repository_id}'. Import it first via POST /repository/import."
            )
        return candidate


git_clone_service = GitService()


# =====================================================================
# 9. Git history / activity / contributors
# =====================================================================

MAX_HISTORY_LIMIT = 200
MAX_FILE_HISTORY_LIMIT = 30
MAX_ACTIVITY_COMMITS = 300
MAX_HOTSPOTS = 10
# Repository-level contributors need the FULL commit history, not the
# recent-activity window above -- but only author identity, never
# `commit.stats` (the expensive per-commit diff computation MAX_ACTIVITY_
# COMMITS exists to bound), so this can afford to look much further back.
# Still capped, as a safety valve for pathologically huge histories rather
# than a limit real repositories are expected to hit.
MAX_CONTRIBUTOR_SCAN_COMMITS = 20_000


def _first_line(message: str) -> str:
    stripped = message.strip()
    return stripped.splitlines()[0] if stripped else "(no commit message)"


def _iso(commit) -> str:
    return commit.committed_datetime.astimezone(timezone.utc).isoformat()


class GitAnalyzer:
    """Reads Git metadata from an already-cloned repository -- commit history,
    per-file history, and repository-wide activity statistics.

    Read-only: never writes, commits, or mutates the repository's Git state.
    """

    def __init__(self, repository_path: Path):
        self.repository_path = repository_path
        self.repo: Repo | None = None
        self.available = False
        try:
            repo = Repo(repository_path)
            repo.head.commit  # touches an unborn HEAD (empty repo) to fail fast, deliberately
            self.repo = repo
            self.available = True
        except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
            self.available = False

    def latest_commit(self) -> "LatestCommit | None":
        if not self.available:
            return None
        commit = self.repo.head.commit
        return LatestCommit(
            hash=commit.hexsha,
            short_hash=commit.hexsha[:7],
            message=_first_line(commit.message),
            author=commit.author.name or "unknown",
            date=_iso(commit),
        )

    def history(self, limit: int) -> tuple[list["CommitEntry"], bool]:
        if not self.available:
            return [], False
        limit = max(1, min(limit, MAX_HISTORY_LIMIT))
        commits = list(self.repo.iter_commits(max_count=limit + 1))
        truncated = len(commits) > limit
        return [self._to_commit_entry(c) for c in commits[:limit]], truncated

    def file_history(self, file_path: str) -> tuple[list["FileCommitEntry"], bool]:
        if not self.available:
            return [], False
        try:
            commits = list(self.repo.iter_commits(paths=file_path, max_count=MAX_FILE_HISTORY_LIMIT + 1))
        except GitCommandError:
            return [], False
        truncated = len(commits) > MAX_FILE_HISTORY_LIMIT
        entries = [
            FileCommitEntry(short_hash=c.hexsha[:7], message=_first_line(c.message), date=_iso(c))
            for c in commits[:MAX_FILE_HISTORY_LIMIT]
        ]
        return entries, truncated

    def repository_contributors(self) -> tuple[int, bool]:
        """Unique commit authors across the FULL commit history -- this is
        what "contributors" means as a repository-level fact (distinct from
        `activity().contributors`, which is deliberately scoped to the last
        MAX_ACTIVITY_COMMITS commits for its diff-stats work and represents
        recent-activity authors, not the repository's all-time contributor
        count). Author identity keys on email first since name alone
        collides more often (shared display names, renamed accounts).

        Returns (count, truncated) -- truncated is only ever true for
        histories longer than MAX_CONTRIBUTOR_SCAN_COMMITS.
        """
        if not self.available:
            return 0, False

        authors: set[str] = set()
        analyzed = 0
        truncated = False
        for commit in self.repo.iter_commits(max_count=MAX_CONTRIBUTOR_SCAN_COMMITS + 1):
            if analyzed >= MAX_CONTRIBUTOR_SCAN_COMMITS:
                truncated = True
                break
            analyzed += 1
            authors.add(commit.author.email or commit.author.name or "unknown")
        return len(authors), truncated

    def activity(self) -> "GitActivityResponse":
        if not self.available:
            return GitActivityResponse(
                total_commits=0,
                contributors=0,
                commits_last_7_days=0,
                commits_last_30_days=0,
                most_modified_files=[],
                analyzed_commit_count=0,
                truncated=False,
            )

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        authors: set[str] = set()
        commits_7d = 0
        commits_30d = 0
        file_counts: dict[str, int] = {}
        analyzed = 0
        truncated = False

        for commit in self.repo.iter_commits(max_count=MAX_ACTIVITY_COMMITS + 1):
            if analyzed >= MAX_ACTIVITY_COMMITS:
                truncated = True
                break
            analyzed += 1
            authors.add(commit.author.email or commit.author.name or "unknown")
            committed_at = commit.committed_datetime.astimezone(timezone.utc)
            if committed_at >= seven_days_ago:
                commits_7d += 1
            if committed_at >= thirty_days_ago:
                commits_30d += 1
            try:
                for filename in commit.stats.files:
                    file_counts[filename] = file_counts.get(filename, 0) + 1
            except (GitCommandError, ValueError):
                continue

        hotspots = sorted(file_counts.items(), key=lambda item: item[1], reverse=True)[:MAX_HOTSPOTS]

        return GitActivityResponse(
            total_commits=analyzed,
            contributors=len(authors),
            commits_last_7_days=commits_7d,
            commits_last_30_days=commits_30d,
            most_modified_files=[HotspotEntry(path=path, commit_count=count) for path, count in hotspots],
            analyzed_commit_count=analyzed,
            truncated=truncated,
        )

    def _to_commit_entry(self, commit) -> "CommitEntry":
        try:
            files_changed = len(commit.stats.files)
        except (GitCommandError, ValueError):
            files_changed = 0
        return CommitEntry(
            hash=commit.hexsha,
            short_hash=commit.hexsha[:7],
            message=_first_line(commit.message),
            author=commit.author.name or "unknown",
            date=_iso(commit),
            files_changed=files_changed,
        )


# =====================================================================
# 10. Pydantic response models
# =====================================================================

# -- Import / analysis -----------------------------------------------


class RepositoryImportRequest(BaseModel):
    github_url: str


class RepositoryImportResponse(BaseModel):
    repository_name: str
    clone_path: str
    status: str


class RepositoryTreeNode(BaseModel):
    name: str
    type: str  # "file" | "directory"
    path: str
    children: list["RepositoryTreeNode"] | None = None


class LargestFile(BaseModel):
    path: str
    size_bytes: int
    lines: int


class Statistics(BaseModel):
    total_lines: int
    largest_file: LargestFile | None


class FileEntry(BaseModel):
    path: str
    extension: str
    language: str
    size_bytes: int
    lines: int
    imports: list[str]


class AnalysisResponse(BaseModel):
    repository_name: str
    total_files: int
    total_folders: int
    languages: dict[str, int]
    frameworks: list[str]
    repository_tree: list[RepositoryTreeNode]
    statistics: Statistics
    files: list[FileEntry]


class RepositoryTreeResponse(BaseModel):
    """The same repository_tree/total_files/total_folders AnalysisResponse
    carries, exposed on its own so the Architecture Repository Map can fetch
    just the tree without pulling the full per-file payload."""

    tree: list[RepositoryTreeNode]
    total_files: int
    total_folders: int


# -- Git ---------------------------------------------------------------


class CommitEntry(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str
    files_changed: int


class LatestCommit(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str


class GitHistoryResponse(BaseModel):
    commits: list[CommitEntry]
    truncated: bool
    has_git_history: bool


class FileCommitEntry(BaseModel):
    short_hash: str
    message: str
    date: str


class FileHistoryResponse(BaseModel):
    file: str
    commits: list[FileCommitEntry]
    truncated: bool
    has_git_history: bool


class HotspotEntry(BaseModel):
    path: str
    commit_count: int


class GitActivityResponse(BaseModel):
    total_commits: int
    contributors: int
    commits_last_7_days: int
    commits_last_30_days: int
    most_modified_files: list[HotspotEntry]
    analyzed_commit_count: int
    truncated: bool


class GitSummaryResponse(BaseModel):
    has_git_history: bool
    latest_commit: LatestCommit | None
    activity: GitActivityResponse
    timeline: list[CommitEntry]
    # Repository-wide unique commit authors (full history) -- the number
    # Overview shows as "contributors". Distinct from `activity.contributors`,
    # which is scoped to the recent analyzed-commit window and labeled as
    # such wherever it's shown (Git History).
    repository_contributors: int
    repository_contributors_truncated: bool


# =====================================================================
# 11. Git service-layer functions -- orchestrate GitAnalyzer against a
#     caller-specified repository (see get_repository_path() above; the
#     caller is api.py, which resolves repository_id to a Path once).
# =====================================================================


def get_commit_history(repository_path: Path, limit: int) -> GitHistoryResponse:
    analyzer = GitAnalyzer(repository_path)
    commits, truncated = analyzer.history(limit)
    return GitHistoryResponse(commits=commits, truncated=truncated, has_git_history=analyzer.available)


def get_file_history(repository_path: Path, file_path: str) -> FileHistoryResponse:
    analyzer = GitAnalyzer(repository_path)
    commits, truncated = analyzer.file_history(file_path)
    return FileHistoryResponse(
        file=file_path, commits=commits, truncated=truncated, has_git_history=analyzer.available
    )


def get_git_summary(repository_path: Path) -> GitSummaryResponse:
    analyzer = GitAnalyzer(repository_path)
    timeline, _ = analyzer.history(15)
    repository_contributors, contributors_truncated = analyzer.repository_contributors()
    return GitSummaryResponse(
        has_git_history=analyzer.available,
        latest_commit=analyzer.latest_commit(),
        activity=analyzer.activity(),
        timeline=timeline,
        repository_contributors=repository_contributors,
        repository_contributors_truncated=contributors_truncated,
    )
