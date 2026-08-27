"""evolution.py -- the Evolution Timeline: groups a repository's real Git
history into "Evolution Areas" (Frontend, Backend, AI, Repository Analysis,
Dependencies, Testing, Documentation, Multi-area, Other) instead of showing
a raw commit list.

This module only ever proves and calculates -- every field on every response
model here is derived directly from repository.py's GitAnalyzer (which reads
real commits, real file paths, real additions/deletions) via deterministic
path/extension/directory rules. Nothing here calls an LLM, guesses, or
infers from commit *message* wording -- classification is 100% structural,
exactly like TechStackDetector and HealthAnalyzer's checks in
repository.py/analyzer.py.

  Git (repository.py's GitAnalyzer.detailed_history)
        |
        v
  classify_file() -- deterministic path/extension/directory rule per file
        |
        v
  classify_commit() -- a commit's area = the one area all its changed files
        |               share, or "Multi-area" if they don't
        v
  group_into_areas() -- merges consecutive same-area commits (within
                         GROUP_GAP_DAYS of each other) into one timeline
                         entry: a period, its commits, its files, its
                         modules
        |
        v
  EvolutionTimelineResponse -- what GET /repository/git/evolution returns

"AI explains" happens entirely through the existing Ask CodeMap chat (see
frontend/src/pages/evolution.jsx's onAskAbout calls) -- this module has no
AI dependency at all. The question text carries the deterministic evidence
computed here; ai.py's existing grounding rules keep the answer honest, the
same way Health and Git History's own "Ask about this" buttons already work.
That's "Git proves -> CodeMap calculates -> AI explains -> UI shows the
evidence" without inventing a second AI code path next to the one that
already exists.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from repository import DetailedCommitEntry, GitAnalyzer, MAX_DETAILED_HISTORY_LIMIT

# =====================================================================
# 1. Deterministic file -> area classification
# =====================================================================

FRONTEND = "Frontend"
BACKEND = "Backend"
AI = "AI"
REPOSITORY_ANALYSIS = "Repository Analysis"
DEPENDENCIES = "Dependencies"
TESTING = "Testing"
DOCUMENTATION = "Documentation"
OTHER = "Other"
MULTI_AREA = "Multi-area"

# Every concrete area a single file can be classified as -- MULTI_AREA is
# never a per-file label, only a per-commit/per-group label applied when a
# commit's files span more than one of these.
AREAS: tuple[str, ...] = (
    DEPENDENCIES,
    TESTING,
    DOCUMENTATION,
    AI,
    REPOSITORY_ANALYSIS,
    FRONTEND,
    BACKEND,
    OTHER,
)

DEPENDENCY_FILENAMES: set[str] = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "composer.json", "composer.lock",
    "gemfile", "gemfile.lock",
}

TEST_PATH_SEGMENTS: tuple[str, ...] = ("tests", "__tests__", "test", "spec")
TEST_FILENAME_MARKERS: tuple[str, ...] = (
    ".test.js", ".test.jsx", ".test.ts", ".test.tsx",
    ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx",
)

DOC_FILENAMES: set[str] = {
    "readme.md", "readme", "readme.rst", "readme.txt",
    "changelog.md", "changelog", "contributing.md",
    "license", "license.md", "code_of_conduct.md",
}
DOC_EXTENSIONS: set[str] = {".md", ".rst", ".adoc"}
DOC_DIR_TOKENS: set[str] = {"docs", "documentation"}

# Directory names and filename-stem tokens (split on -, _, .) that signal
# AI/LLM-related code -- deliberately whole-token matches (e.g. the stem
# "ai" matches ai.py, but the stem "aiport" does not), so this can't false-
# positive on an unrelated file that merely contains the substring "ai".
AI_DIR_TOKENS: set[str] = {"ai", "llm", "ml", "genai"}
AI_NAME_TOKENS: set[str] = {
    "ai", "llm", "gpt", "openai", "anthropic", "langchain", "embedding",
    "embeddings", "prompt", "prompts", "chatbot", "chat", "assistant",
    "rag", "vectorstore",
}

# A repository's own code-analysis engine (parsers, scanners, dependency
# graph builders) -- the area name CodeMap uses for its own analyzer.py/
# repository.py, generalized to any repository with an equivalent layer.
REPO_ANALYSIS_DIR_TOKENS: set[str] = {"analyzer", "analyzers", "analysis", "parser", "parsers", "scanner", "scanners"}
REPO_ANALYSIS_NAME_TOKENS: set[str] = {
    "analyzer", "analyzers", "analysis", "analyses", "parser", "parsers",
    "scanner", "scanners", "indexer", "indexers", "extractor", "extractors",
    "codeintel", "codeintelligence", "ast",
}

FRONTEND_DIR_TOKENS: set[str] = {"frontend", "client", "web", "ui", "public"}
FRONTEND_EXTENSIONS: set[str] = {".jsx", ".tsx", ".vue", ".svelte", ".css", ".scss", ".sass", ".less", ".html"}

BACKEND_DIR_TOKENS: set[str] = {"backend", "server", "api"}
BACKEND_EXTENSIONS: set[str] = {".py", ".go", ".rb", ".php", ".java", ".kt", ".cs", ".rs"}

# Ambiguous between frontend and backend on extension alone (a Node backend
# and a browser bundle both use these) -- resolved by directory tokens
# above first; only reaches here with no directory signal either way, so
# defaults to Frontend as the more common case for a bare .js/.ts file.
AMBIGUOUS_SCRIPT_EXTENSIONS: set[str] = {".js", ".ts", ".mjs", ".cjs"}

_TOKEN_SPLIT_PATTERN = re.compile(r"[-_.]+")


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.lower().split("/") if segment]


def _stem_tokens(filename: str) -> set[str]:
    stem = PurePosixPath(filename).stem.lower()
    return set(_TOKEN_SPLIT_PATTERN.split(stem))


def _is_test_path(path: str, filename: str) -> bool:
    segments = _path_segments(path)
    if any(segment in TEST_PATH_SEGMENTS for segment in segments[:-1]):
        return True
    lower_name = filename.lower()
    if lower_name.startswith("test_") or lower_name.endswith("_test.py"):
        return True
    return any(lower_name.endswith(marker) for marker in TEST_FILENAME_MARKERS)


def classify_file(path: str) -> str:
    """Deterministically classifies one changed file path into exactly one
    area, using only the path itself -- its filename, extension, and
    directory segments. No commit metadata, no file content, no AI."""
    filename = PurePosixPath(path).name
    lower_name = filename.lower()
    extension = PurePosixPath(path).suffix.lower()
    directories = _path_segments(path)[:-1]
    stem_tokens = _stem_tokens(filename)

    if lower_name in DEPENDENCY_FILENAMES:
        return DEPENDENCIES

    if _is_test_path(path, filename):
        return TESTING

    if lower_name in DOC_FILENAMES or extension in DOC_EXTENSIONS or any(d in DOC_DIR_TOKENS for d in directories):
        return DOCUMENTATION

    if any(d in AI_DIR_TOKENS for d in directories) or (stem_tokens & AI_NAME_TOKENS):
        return AI

    if any(d in REPO_ANALYSIS_DIR_TOKENS for d in directories) or (stem_tokens & REPO_ANALYSIS_NAME_TOKENS):
        return REPOSITORY_ANALYSIS

    if any(d in FRONTEND_DIR_TOKENS for d in directories) or extension in FRONTEND_EXTENSIONS:
        return FRONTEND

    if any(d in BACKEND_DIR_TOKENS for d in directories) or extension in BACKEND_EXTENSIONS:
        return BACKEND

    if extension in AMBIGUOUS_SCRIPT_EXTENSIONS:
        return FRONTEND

    return OTHER


# =====================================================================
# 2. Per-commit classification
# =====================================================================


class EvolutionCommit(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str
    additions: int
    deletions: int
    files_changed: int
    area: str
    area_breakdown: dict[str, int]
    files: list[str]


def classify_commit(commit: DetailedCommitEntry, *, max_files: int) -> EvolutionCommit:
    breakdown: dict[str, int] = {}
    for file_change in commit.files:
        file_area = classify_file(file_change.path)
        breakdown[file_area] = breakdown.get(file_area, 0) + 1

    area = next(iter(breakdown)) if len(breakdown) == 1 else (MULTI_AREA if breakdown else OTHER)

    return EvolutionCommit(
        hash=commit.hash,
        short_hash=commit.short_hash,
        message=commit.message,
        author=commit.author,
        date=commit.date,
        additions=commit.additions,
        deletions=commit.deletions,
        files_changed=len(commit.files),
        area=area,
        area_breakdown=breakdown,
        files=[f.path for f in commit.files[:max_files]],
    )


# =====================================================================
# 3. Grouping classified commits into Evolution Areas
# =====================================================================

# Consecutive commits sharing the same area merge into one timeline entry
# as long as no gap between them exceeds this -- long enough that a normal
# few-day-old feature branch's commits stay one period, short enough that
# unrelated work on the same area months apart stays two.
GROUP_GAP_DAYS = 21

MAX_FILES_PER_AREA = 80
MAX_MODULES_PER_AREA = 15
MAX_FILES_PER_COMMIT_EVIDENCE = 40


class EvolutionArea(BaseModel):
    id: str
    area: str
    period_start: str
    period_end: str
    commit_count: int
    additions: int
    deletions: int
    files: list[str]
    files_truncated: bool
    modules: list[str]
    area_breakdown: dict[str, int]
    commits: list[EvolutionCommit]


class EvolutionTimelineResponse(BaseModel):
    has_git_history: bool
    areas: list[EvolutionArea]
    analyzed_commit_count: int
    truncated: bool


def _module_for(path: str) -> str:
    segments = path.split("/")
    return segments[0] if len(segments) > 1 else path


def _finalize_group(commits: list[EvolutionCommit]) -> EvolutionArea:
    # `commits` is chronological ascending within the group; the timeline
    # itself is presented newest-first (see build_evolution_timeline), but
    # a group's own period reads oldest -> newest.
    area = commits[0].area
    all_files: list[str] = []
    seen_files: set[str] = set()
    modules: list[str] = []
    seen_modules: set[str] = set()
    breakdown: dict[str, int] = {}

    for commit in commits:
        for file_area, count in commit.area_breakdown.items():
            breakdown[file_area] = breakdown.get(file_area, 0) + count
        for path in commit.files:
            if path not in seen_files:
                seen_files.add(path)
                all_files.append(path)
            module = _module_for(path)
            if module not in seen_modules:
                seen_modules.add(module)
                modules.append(module)

    files_truncated = len(all_files) > MAX_FILES_PER_AREA
    return EvolutionArea(
        id=f"{area.lower().replace(' ', '-')}-{commits[0].short_hash}",
        area=area,
        period_start=commits[0].date,
        period_end=commits[-1].date,
        commit_count=len(commits),
        additions=sum(c.additions for c in commits),
        deletions=sum(c.deletions for c in commits),
        files=sorted(all_files)[:MAX_FILES_PER_AREA],
        files_truncated=files_truncated,
        modules=sorted(modules)[:MAX_MODULES_PER_AREA],
        area_breakdown=breakdown,
        commits=commits,
    )


def group_into_areas(commits_newest_first: list[EvolutionCommit]) -> list[EvolutionArea]:
    """Merges consecutive same-area commits (within GROUP_GAP_DAYS) into
    Evolution Area entries. Walks oldest-to-newest so "consecutive" means
    what it should chronologically, then returns newest-period-first to
    match every other timeline in this app (Git History's commit list,
    Health's findings)."""
    commits_oldest_first = list(reversed(commits_newest_first))

    groups: list[list[EvolutionCommit]] = []
    current: list[EvolutionCommit] = []
    current_last_date: datetime | None = None

    for commit in commits_oldest_first:
        commit_date = datetime.fromisoformat(commit.date)
        same_area = current and current[-1].area == commit.area
        within_gap = current_last_date is not None and (commit_date - current_last_date) <= timedelta(days=GROUP_GAP_DAYS)

        if current and same_area and within_gap:
            current.append(commit)
        else:
            if current:
                groups.append(current)
            current = [commit]
        current_last_date = commit_date

    if current:
        groups.append(current)

    areas = [_finalize_group(group) for group in groups]
    areas.reverse()
    return areas


# =====================================================================
# 4. Orchestration -- what api.py's route calls
# =====================================================================


def build_evolution_timeline(repository_path: Path, limit: int = MAX_DETAILED_HISTORY_LIMIT) -> EvolutionTimelineResponse:
    analyzer = GitAnalyzer(repository_path)
    detailed_commits, truncated = analyzer.detailed_history(limit)

    if not detailed_commits:
        return EvolutionTimelineResponse(
            has_git_history=analyzer.available,
            areas=[],
            analyzed_commit_count=0,
            truncated=False,
        )

    classified = [classify_commit(c, max_files=MAX_FILES_PER_COMMIT_EVIDENCE) for c in detailed_commits]
    areas = group_into_areas(classified)

    return EvolutionTimelineResponse(
        has_git_history=True,
        areas=areas,
        analyzed_commit_count=len(classified),
        truncated=truncated,
    )
