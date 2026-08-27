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

from analyzer import RelationshipIndex, get_or_build_code_intelligence
from repository import (
    DetailedCommitEntry,
    GitAnalyzer,
    ImportExtractor,
    JS_IMPORT_EXTENSIONS,
    MAX_DETAILED_HISTORY_LIMIT,
    PYTHON_IMPORT_EXTENSIONS,
    get_repository_snapshot,
)

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


# =====================================================================
# 5. Change Impact for an Evolution Area
#
# When a user opens an area, its impact is calculated -- never guessed by
# an LLM -- from two sources of real evidence:
#   - repository.py's GitAnalyzer: the area's own commits' real per-file
#     additions/deletions, and (bounded) their real diff text for import
#     line changes.
#   - analyzer.py's RelationshipIndex: the same import/call graph
#     GraphBuilder, ImpactAnalyzer, and HealthAnalyzer's coupling check
#     already build from Day 3 code intelligence -- reused here rather
#     than rebuilt, so "9 direct dependents" means the same thing here as
#     it does in Architecture's own Impact mode.
#
# Every score component is normalized against THIS repository's own
# averages (connectivity per file, symbols per file, churn as a share of
# the repo's own size) rather than fixed magic numbers -- a file with 9
# dependents is only meaningfully "highly connected" relative to what's
# typical in a given repository; 9 is unremarkable in a large monorepo and
# extreme in a 20-file project. See calibration_note on the response,
# which states the exact baseline used. Only the cross-layer bonus and the
# import-diff-count weight stay fixed, small counts -- "spans 2 areas" and
# "3 import lines changed" are already inherently repo-size-independent
# facts, not magnitudes that need normalizing.
# =====================================================================

IMPORT_SCANNABLE_EXTENSIONS: set[str] = JS_IMPORT_EXTENSIONS | PYTHON_IMPORT_EXTENSIONS
# Bounds how many (commit, file) diffs get fetched to count import
# add/remove lines -- each is a real `git diff` invocation, so this is a
# genuine cost control, not a display truncation. Large areas still get a
# score; import_changes.truncated just says the count is a partial sample.
MAX_IMPORT_DIFF_LOOKUPS = 40

MAX_FILE_CONNECTIVITY_EVIDENCE = 15

CONNECTIVITY_WEIGHT = 40
CHURN_WEIGHT = 20
CROSS_LAYER_WEIGHT = 15
SYMBOL_WEIGHT = 15
IMPORT_CHANGE_WEIGHT = 10

# The composite 0-100 score is already repo-calibrated by the ratios that
# feed it (see module docstring above), so bucketing that normalized scale
# at even thirds is not an arbitrary absolute threshold on raw counts --
# it's "meaningfully above this repo's own average" (medium) vs. "well
# above it" (high).
HIGH_IMPACT_SCORE = 60
MEDIUM_IMPACT_SCORE = 30


class FileConnectivity(BaseModel):
    path: str
    fan_in: int
    fan_out: int
    functions: int
    classes: int


class ImportChangeSummary(BaseModel):
    added: int
    removed: int
    files_scanned: int
    truncated: bool


class ImpactScoreBreakdown(BaseModel):
    connectivity: int
    churn: int
    cross_layer: int
    symbols: int
    dependency_changes: int


class AreaImpact(BaseModel):
    area_id: str
    score: int
    level: str  # "low" | "medium" | "high"
    headline: str
    reasons: list[str]
    breakdown: ImpactScoreBreakdown
    files_changed: int
    additions: int
    deletions: int
    architectural_areas: list[str]
    modules: list[str]
    most_central_file: str | None
    most_central_file_fan_in: int
    relationships_touched: int
    file_connectivity: list[FileConnectivity]
    import_changes: ImportChangeSummary
    calibration_note: str


def _join_clauses(clauses: list[str]) -> str:
    if not clauses:
        return "no dependents or dependency relationships were found for the files it touched"
    if len(clauses) == 1:
        return clauses[0]
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _scan_import_changes(
    analyzer: GitAnalyzer, commits: list[DetailedCommitEntry]
) -> ImportChangeSummary:
    added = 0
    removed = 0
    files_scanned = 0
    truncated = False

    for commit in commits:
        for file_change in commit.files:
            extension = PurePosixPath(file_change.path).suffix.lower()
            if extension not in IMPORT_SCANNABLE_EXTENSIONS:
                continue
            if files_scanned >= MAX_IMPORT_DIFF_LOOKUPS:
                truncated = True
                break
            diff = analyzer.commit_diff(commit.hash, file_change.path)
            files_scanned += 1
            if not diff:
                continue
            for line in diff.splitlines():
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if line.startswith("+") and ImportExtractor.extract(line[1:], extension):
                    added += 1
                elif line.startswith("-") and ImportExtractor.extract(line[1:], extension):
                    removed += 1
        if truncated:
            break

    return ImportChangeSummary(added=added, removed=removed, files_scanned=files_scanned, truncated=truncated)


def compute_area_impact(repository_path: Path, area_id: str, limit: int = MAX_DETAILED_HISTORY_LIMIT) -> AreaImpact | None:
    """Returns None if `area_id` doesn't match any area the current commit
    window produces -- api.py maps that to a 404 rather than a stale/wrong
    impact result (an area regrouping across an import bound change, for
    instance, must never silently score the wrong commits)."""
    timeline = build_evolution_timeline(repository_path, limit)
    area = next((a for a in timeline.areas if a.id == area_id), None)
    if area is None:
        return None

    git_analyzer = GitAnalyzer(repository_path)
    hashes = {c.hash for c in area.commits}
    # Re-reads the same bounded commit window build_evolution_timeline just
    # used, but this time keeps every file per commit (EvolutionCommit.files
    # is capped for display -- see MAX_FILES_PER_COMMIT_EVIDENCE) so the
    # impact math below is computed against the area's real, complete file
    # set, not a display-truncated one.
    all_detailed, _truncated = git_analyzer.detailed_history(limit)
    area_commits = [c for c in all_detailed if c.hash in hashes]

    touched_files: list[str] = []
    seen_files: set[str] = set()
    for commit in area_commits:
        for file_change in commit.files:
            if file_change.path not in seen_files:
                seen_files.add(file_change.path)
                touched_files.append(file_change.path)

    files_changed = len(touched_files)
    additions = sum(c.additions for c in area_commits)
    deletions = sum(c.deletions for c in area_commits)

    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)

    # -- Connectivity: how central are the touched files in the real import/
    #    call graph, relative to this repository's own average. --
    connectivity: list[FileConnectivity] = []
    symbols_by_file: dict[str, tuple[int, int]] = {}
    for symbol in intelligence["symbols"]:
        functions, classes = symbols_by_file.get(symbol["file"], (0, 0))
        if symbol["kind"] == "function":
            functions += 1
        elif symbol["kind"] == "class":
            classes += 1
        symbols_by_file[symbol["file"]] = (functions, classes)

    for path in touched_files:
        if path not in index.file_paths:
            continue
        fan_in = len(index.reverse(path))
        fan_out = len(index.forward(path))
        functions, classes = symbols_by_file.get(path, (0, 0))
        connectivity.append(FileConnectivity(path=path, fan_in=fan_in, fan_out=fan_out, functions=functions, classes=classes))

    # Ranked by fan_in first -- how many other files depend on it is the
    # more central/risky signal (matches "has N direct dependents" in the
    # headline), fan_out as a tiebreaker only.
    connectivity.sort(key=lambda f: (f.fan_in, f.fan_out), reverse=True)
    most_central = connectivity[0] if connectivity else None
    relationships_touched = sum(f.fan_in + f.fan_out for f in connectivity)
    touched_connected_count = len(connectivity)

    total_repo_files = len(index.file_paths)
    repo_total_relationships = sum(len(index.reverse(p)) + len(index.forward(p)) for p in index.file_paths)
    repo_avg_relationships_per_file = (repo_total_relationships / total_repo_files) if total_repo_files else 0.0

    if repo_avg_relationships_per_file > 0 and touched_connected_count > 0:
        connectivity_ratio = relationships_touched / (repo_avg_relationships_per_file * touched_connected_count)
    else:
        connectivity_ratio = 1.0 if relationships_touched > 0 else 0.0
    connectivity_score = round(CONNECTIVITY_WEIGHT * min(connectivity_ratio, 2) / 2)

    # -- Churn: how much of the repository's own size did this area touch. --
    total_repo_source_files = day2_result.total_files or 1
    total_repo_lines = day2_result.statistics.get("total_lines") or 1
    files_ratio = files_changed / total_repo_source_files
    lines_ratio = (additions + deletions) / total_repo_lines
    churn_score = round(CHURN_WEIGHT * min(files_ratio * 10 + lines_ratio * 10, 1))

    # -- Cross-layer span: a structural, repo-size-independent fact. --
    distinct_areas = [a for a in area.area_breakdown if area.area_breakdown[a] > 0]
    cross_layer_score = min(CROSS_LAYER_WEIGHT, max(0, len(distinct_areas) - 1) * 8)

    # -- Symbol surface: functions/classes defined in the touched files,
    #    relative to this repository's own average symbols-per-file. --
    symbol_count = sum(symbols_by_file.get(path, (0, 0))[0] + symbols_by_file.get(path, (0, 0))[1] for path in touched_files)
    total_symbols = len(intelligence["symbols"])
    repo_avg_symbols_per_file = (total_symbols / total_repo_files) if total_repo_files else 0.0
    touched_parseable_count = sum(1 for path in touched_files if path in symbols_by_file or path in index.file_paths)
    if repo_avg_symbols_per_file > 0 and touched_parseable_count > 0:
        symbol_ratio = symbol_count / (repo_avg_symbols_per_file * touched_parseable_count)
    else:
        symbol_ratio = 1.0 if symbol_count > 0 else 0.0
    symbol_score = round(SYMBOL_WEIGHT * min(symbol_ratio, 2) / 2)

    # -- Dependency/import churn: real added/removed import lines from the
    #    area's actual diffs (bounded -- see MAX_IMPORT_DIFF_LOOKUPS). A
    #    small absolute count by nature, so a fixed (not repo-relative)
    #    weight is appropriate here, unlike connectivity/churn/symbols above.
    import_changes = _scan_import_changes(git_analyzer, area_commits)
    import_change_score = min(IMPORT_CHANGE_WEIGHT, (import_changes.added + import_changes.removed) * 2)

    score = connectivity_score + churn_score + cross_layer_score + symbol_score + import_change_score
    score = max(0, min(100, score))

    if score >= HIGH_IMPACT_SCORE:
        level = "high"
    elif score >= MEDIUM_IMPACT_SCORE:
        level = "medium"
    else:
        level = "low"

    clauses: list[str] = []
    if most_central and most_central.fan_in > 0:
        clauses.append(f"{most_central.path} was modified")
        clauses.append(f"has {most_central.fan_in} direct dependent{'s' if most_central.fan_in != 1 else ''}")
    if relationships_touched > 0:
        clauses.append(
            f"the change affected {relationships_touched} dependency relationship{'s' if relationships_touched != 1 else ''}"
        )
    if len(distinct_areas) > 1:
        clauses.append(f"it spans {len(distinct_areas)} architectural areas ({', '.join(sorted(distinct_areas))})")
    if not clauses:
        clauses.append(f"{files_changed} file(s) changed with no dependents found in the current import graph")

    headline = f"{level.capitalize()} impact because {_join_clauses(clauses)}."

    reasons = [
        f"{files_changed} file(s) changed, +{additions}/-{deletions} lines "
        f"({files_ratio * 100:.1f}% of this repository's files, {lines_ratio * 100:.1f}% of its total lines).",
    ]
    if most_central:
        reasons.append(
            f"Most connected file: {most_central.path} -- {most_central.fan_in} file(s) depend on it, "
            f"it depends on {most_central.fan_out}."
        )
    if relationships_touched > 0:
        reasons.append(
            f"{relationships_touched} total dependency relationship(s) touched across "
            f"{touched_connected_count} file(s) present in the import/call graph."
        )
    if len(distinct_areas) > 1:
        reasons.append(f"Cross-layer change: spans {', '.join(sorted(distinct_areas))}.")
    if symbol_count > 0:
        reasons.append(f"{symbol_count} function(s)/class(es) defined in the changed files (current state).")
    if import_changes.files_scanned > 0:
        reasons.append(
            f"{import_changes.added} import statement(s) added, {import_changes.removed} removed, "
            f"across {import_changes.files_scanned} scanned diff(s)"
            f"{' (bounded sample)' if import_changes.truncated else ''}."
        )

    calibration_note = (
        f"Calibrated against this repository's own averages: {repo_avg_relationships_per_file:.1f} "
        f"dependency relationship(s) per file and {repo_avg_symbols_per_file:.1f} function(s)/class(es) "
        f"per file, across {total_repo_files} file(s) in the dependency graph -- not a fixed, "
        f"repository-independent threshold."
    )

    return AreaImpact(
        area_id=area.id,
        score=score,
        level=level,
        headline=headline,
        reasons=reasons,
        breakdown=ImpactScoreBreakdown(
            connectivity=connectivity_score,
            churn=churn_score,
            cross_layer=cross_layer_score,
            symbols=symbol_score,
            dependency_changes=import_change_score,
        ),
        files_changed=files_changed,
        additions=additions,
        deletions=deletions,
        architectural_areas=sorted(distinct_areas),
        modules=area.modules,
        most_central_file=most_central.path if most_central else None,
        most_central_file_fan_in=most_central.fan_in if most_central else 0,
        relationships_touched=relationships_touched,
        file_connectivity=connectivity[:MAX_FILE_CONNECTIVITY_EVIDENCE],
        import_changes=import_changes,
        calibration_note=calibration_note,
    )
