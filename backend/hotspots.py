"""hotspots.py -- Code Hotspots: which files are under the most pressure,
scored deterministically from real Git change frequency/recency
(repository.py's GitAnalyzer.file_activity) combined with real dependency
connectivity (analyzer.py's RelationshipIndex -- the same graph Change
Impact and Architecture Drift use) -- never an AI-assigned rating.

A hotspot is NOT "most commits." Four independent, real signals feed the
score:
  - change frequency  -- how often this file has changed (Git)
  - recent activity   -- how often it has changed lately (Git)
  - connectivity      -- how many files directly depend on / are depended
                          on by it (the repository's dependency graph)
  - relationship density -- how much of the WHOLE graph's connections run
                          through this one file (the same graph, a
                          different cut of it)

Every component is calibrated against this repository's own average for
that signal (see CALIBRATION_* constants and Hotspot.calibration_note) --
"34 commits" is only meaningfully high relative to what's typical in a
given repository, so scoring never compares raw counts to a fixed,
repository-independent number.

Git proves -> CodeMap calculates -> AI explains -> UI shows the evidence:
this module only proves and calculates. "Explain" reuses the existing Ask
CodeMap chat, the same way Evolution Timeline and Change Impact's own
"Explain"/"Ask about this" buttons already do -- no separate AI scoring
path exists here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from analyzer import RelationshipIndex, get_or_build_code_intelligence
from repository import GitAnalyzer, MAX_ACTIVITY_COMMITS, get_repository_snapshot

# =====================================================================
# Tuning constants
# =====================================================================

RECENT_ACTIVITY_DAYS = 90
# How many of the most-frequently-changed (still-existing) files get a full
# score computed -- scoring touches the dependency graph per candidate, so
# this bounds that work on a repository with a huge number of touched files.
CANDIDATE_POOL_SIZE = 30
TOP_HOTSPOTS = 10
RECENT_COMMIT_EVIDENCE_LIMIT = 5

CHANGE_FREQUENCY_WEIGHT = 30
RECENT_ACTIVITY_WEIGHT = 20
CONNECTIVITY_WEIGHT = 30
DENSITY_WEIGHT = 20

# Change frequency is typically power-law distributed (a handful of files
# change constantly, most change once or twice) -- capping the ratio at 3x
# the repo's own average change frequency before a candidate maxes out this
# component keeps that skew from making every touched file look "hot"
# relative to a mean dragged down by hundreds of once-touched files.
CHANGE_FREQUENCY_RATIO_CAP = 3
RECENT_ACTIVITY_RATIO_CAP = 3
CONNECTIVITY_RATIO_CAP = 2
DENSITY_RATIO_CAP = 3

HIGH_HOTSPOT_SCORE = 60
MEDIUM_HOTSPOT_SCORE = 30


class HotspotCommitEvidence(BaseModel):
    short_hash: str
    message: str
    date: str


class Hotspot(BaseModel):
    path: str
    score: int
    level: str  # "low" | "medium" | "high"
    why: str
    total_commits: int
    recent_commits: int
    last_modified: str
    direct_dependents: int
    direct_dependencies: int
    relationships: int
    functions: int
    classes: int
    recent_commit_evidence: list[HotspotCommitEvidence]
    calibration_note: str


class HotspotsResponse(BaseModel):
    has_git_history: bool
    hotspots: list[Hotspot]
    analyzed_commit_count: int
    truncated: bool
    recent_activity_days: int


def _ratio_score(value: float, average: float, weight: int, cap: float) -> int:
    """Scores `value` relative to this repository's own `average` for the
    same signal, not a fixed threshold -- a ratio of 1.0 (exactly average)
    scores half the weight; `cap`x average or more scores the full weight.
    Falls back to a binary any-signal-at-all score when there's no
    meaningful average to compare against (e.g. a repository with no
    dependency graph at all)."""
    if average <= 0:
        return weight if value > 0 else 0
    ratio = value / average
    return round(weight * min(ratio, cap) / cap)


def compute_hotspots(
    repository_path: Path,
    limit: int = MAX_ACTIVITY_COMMITS,
    recent_days: int = RECENT_ACTIVITY_DAYS,
    top_n: int = TOP_HOTSPOTS,
) -> HotspotsResponse:
    git_analyzer = GitAnalyzer(repository_path)
    activity, analyzed_commit_count, truncated = git_analyzer.file_activity(limit, recent_days)

    if not activity:
        return HotspotsResponse(
            has_git_history=git_analyzer.available,
            hotspots=[],
            analyzed_commit_count=analyzed_commit_count,
            truncated=truncated,
            recent_activity_days=recent_days,
        )

    day2_result = get_repository_snapshot(repository_path)
    # A hotspot is about pressure on the repository AS IT EXISTS TODAY -- a
    # file Git shows heavy historical churn for but that was later deleted
    # or renamed away isn't "under pressure" now, so candidates are
    # restricted to files the current canonical snapshot still contains.
    current_paths = {entry["path"] for entry in day2_result.files}
    candidates = sorted(
        (stats for path, stats in activity.items() if path in current_paths),
        key=lambda s: s.total_commits,
        reverse=True,
    )[:CANDIDATE_POOL_SIZE]

    if not candidates:
        return HotspotsResponse(
            has_git_history=True,
            hotspots=[],
            analyzed_commit_count=analyzed_commit_count,
            truncated=truncated,
            recent_activity_days=recent_days,
        )

    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)

    symbols_by_file: dict[str, tuple[int, int]] = {}
    for symbol in intelligence["symbols"]:
        functions, classes = symbols_by_file.get(symbol["file"], (0, 0))
        if symbol["kind"] == "function":
            functions += 1
        elif symbol["kind"] == "class":
            classes += 1
        symbols_by_file[symbol["file"]] = (functions, classes)

    # -- Repository-wide baselines every candidate's signals are scored
    #    against, computed once, over the SAME candidate pool being ranked
    #    (not the whole repository) -- what "average" means here is "average
    #    among files that are already at least somewhat active/connected,"
    #    the same population a candidate is actually being compared to.
    avg_total_commits = sum(s.total_commits for s in candidates) / len(candidates)
    avg_recent_commits = sum(s.recent_commits for s in candidates) / len(candidates)

    connectivity_by_path: dict[str, tuple[int, int]] = {}
    relationships_sum = 0
    for stats in candidates:
        fan_in = len(index.reverse(stats.path))
        fan_out = len(index.forward(stats.path))
        connectivity_by_path[stats.path] = (fan_in, fan_out)
        relationships_sum += fan_in + fan_out
    avg_connectivity = relationships_sum / len(candidates)
    avg_density_share = (1 / len(candidates)) if relationships_sum > 0 else 0

    scored: list[tuple[int, Hotspot]] = []
    for stats in candidates:
        fan_in, fan_out = connectivity_by_path[stats.path]
        relationships = fan_in + fan_out
        functions, classes = symbols_by_file.get(stats.path, (0, 0))
        density_share = (relationships / relationships_sum) if relationships_sum > 0 else 0

        change_frequency_score = _ratio_score(
            stats.total_commits, avg_total_commits, CHANGE_FREQUENCY_WEIGHT, CHANGE_FREQUENCY_RATIO_CAP
        )
        recent_activity_score = _ratio_score(
            stats.recent_commits, avg_recent_commits, RECENT_ACTIVITY_WEIGHT, RECENT_ACTIVITY_RATIO_CAP
        )
        connectivity_score = _ratio_score(relationships, avg_connectivity, CONNECTIVITY_WEIGHT, CONNECTIVITY_RATIO_CAP)
        density_score = _ratio_score(density_share, avg_density_share, DENSITY_WEIGHT, DENSITY_RATIO_CAP)

        score = max(0, min(100, change_frequency_score + recent_activity_score + connectivity_score + density_score))
        if score >= HIGH_HOTSPOT_SCORE:
            level = "high"
        elif score >= MEDIUM_HOTSPOT_SCORE:
            level = "medium"
        else:
            level = "low"

        why_clauses: list[str] = []
        if stats.total_commits > avg_total_commits:
            why_clauses.append(f"frequently modified ({stats.total_commits} commits)")
        if relationships > avg_connectivity and relationships > 0:
            why_clauses.append(f"highly connected to the rest of the codebase ({relationships} relationships)")
        if stats.recent_commits > avg_recent_commits and stats.recent_commits > 0:
            why_clauses.append(f"active recently ({stats.recent_commits} commits in the last {recent_days} days)")
        if not why_clauses:
            why_clauses.append(f"changed {stats.total_commits} time(s) with below-average connectivity for this repository")
        if len(why_clauses) == 1:
            joined = why_clauses[0]
        else:
            joined = ", ".join(why_clauses[:-1]) + ", and " + why_clauses[-1]
        why = joined[0].upper() + joined[1:] + "."

        commit_history, _truncated = git_analyzer.file_history(stats.path)
        recent_evidence = [
            HotspotCommitEvidence(short_hash=c.short_hash, message=c.message, date=c.date)
            for c in commit_history[:RECENT_COMMIT_EVIDENCE_LIMIT]
        ]

        calibration_note = (
            f"Calibrated against the {len(candidates)} most-changed files still in this repository: "
            f"{avg_total_commits:.1f} commits/file on average, {avg_connectivity:.1f} dependency "
            f"relationship(s)/file on average -- not a fixed, repository-independent threshold."
        )

        hotspot = Hotspot(
            path=stats.path,
            score=score,
            level=level,
            why=why,
            total_commits=stats.total_commits,
            recent_commits=stats.recent_commits,
            last_modified=stats.last_modified,
            direct_dependents=fan_in,
            direct_dependencies=fan_out,
            relationships=relationships,
            functions=functions,
            classes=classes,
            recent_commit_evidence=recent_evidence,
            calibration_note=calibration_note,
        )
        scored.append((score, hotspot))

    scored.sort(key=lambda item: item[0], reverse=True)

    return HotspotsResponse(
        has_git_history=True,
        hotspots=[hotspot for _score, hotspot in scored[:top_n]],
        analyzed_commit_count=analyzed_commit_count,
        truncated=truncated,
        recent_activity_days=recent_days,
    )
