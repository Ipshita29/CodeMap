"""architecture_drift.py -- Architecture Drift: how has this repository's
dependency graph actually changed over time.

Never fakes history by relabeling today's graph. For each historical
checkpoint this module:
  1. picks a REAL commit (repository.py's GitAnalyzer.commit_refs) --
     never an invented date
  2. materializes that commit's actual tree to a scratch directory
     (GitAnalyzer.materialize_commit) -- real blob content, nothing
     interpolated
  3. runs the exact same RepositoryAnalyzer + CodeIntelligenceAnalyzer
     pipeline used for the live repository against it (the same classes
     Architecture/Health/Change Impact/Evolution Timeline all build on) --
     so a historical snapshot is comparable to today's, not a different
     methodology
  4. builds a RelationshipIndex (analyzer.py, reused) and reduces it to a
     handful of deterministic metrics
  5. caches the result, keyed on (repository path, commit SHA, analysis
     version) -- a commit's tree never changes, so once computed a
     checkpoint's snapshot is reused forever for that repository, never
     recomputed on the next request

The "today" checkpoint never goes through steps 2-3 at all -- it reuses
the exact same live get_repository_snapshot()/get_or_build_code_intelligence()
cache Architecture and Change Impact already read from, so there is only
ever one live analysis pass per repository version, no matter how many
features consume it.

Git proves -> CodeMap calculates -> AI explains -> UI shows the evidence:
every module_count/relationship_count/percent_change here is arithmetic
over real snapshots. Nothing here is AI-generated; "explain" reuses the
existing Ask CodeMap chat exactly like Evolution Timeline, Change Impact,
and Hotspots already do.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from analyzer import CodeIntelligenceAnalyzer, RelationshipIndex, get_or_build_code_intelligence
from config import settings
from repository import CommitRef, GitAnalyzer, MAX_DETAILED_HISTORY_LIMIT, RepositoryAnalyzer, get_repository_snapshot
from utils import RepositoryAnalysisError

# =====================================================================
# Checkpoint selection -- real commits, never invented dates
# =====================================================================

# Preferred calendar look-back points, in days before the most recent
# analyzed commit -- used only when the repository's actual history spans
# enough real time (see MIN_CALENDAR_SPAN_DAYS) for these to land on
# genuinely distinct commits with genuinely distinct labels.
CALENDAR_TARGETS_DAYS_AGO: tuple[int, ...] = (180, 90, 30)
MIN_CALENDAR_SPAN_DAYS = 60
MAX_CHECKPOINTS = 5
MAX_MIDDLE_CHECKPOINTS = 3


def _relative_label(checkpoint_date: datetime, head_date: datetime) -> str:
    total_seconds = (head_date - checkpoint_date).total_seconds()
    if total_seconds <= 0:
        return "Today"
    hours = total_seconds / 3600
    # Sub-day granularity first -- without it, every commit made earlier the
    # same calendar day as the most recent one collapses to the same "Today"
    # label as the head checkpoint itself, which is a real, distinct commit.
    if hours < 20:
        rounded_hours = max(1, round(hours))
        return f"{rounded_hours} hour{'s' if rounded_hours != 1 else ''} ago"
    days = (head_date - checkpoint_date).days
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 60:
        weeks = round(days / 7)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = round(days / 30)
    return f"{months} month{'s' if months != 1 else ''} ago"


def _pick_calendar_checkpoints(commit_refs: list[CommitRef], head_date: datetime, earliest_date: datetime) -> list[CommitRef]:
    picks: list[CommitRef] = []
    for days_ago in CALENDAR_TARGETS_DAYS_AGO:
        target_date = head_date - timedelta(days=days_ago)
        if target_date <= earliest_date:
            continue  # the repository's history doesn't reach back this far
        nearest = min(commit_refs, key=lambda c: abs(datetime.fromisoformat(c.date) - target_date))
        picks.append(nearest)
    return picks


def _pick_time_spread_checkpoints(
    commit_refs: list[CommitRef], head_date: datetime, earliest_date: datetime, count: int
) -> list[CommitRef]:
    """Divides the repository's OWN actual timespan (earliest commit to
    head) into `count` equal intervals and picks the real commit nearest
    each interior boundary. Used when the repository doesn't span enough
    calendar time for 6/3/1-month-ago to mean anything (a young repository,
    or one with a burst of many commits close together in time) -- spreads
    checkpoints across real elapsed time rather than by commit-index
    position, which a burst of commits would otherwise cluster together."""
    span_seconds = (head_date - earliest_date).total_seconds()
    if span_seconds <= 0 or count <= 0:
        return []
    picks: list[CommitRef] = []
    for i in range(1, count + 1):
        target = earliest_date + timedelta(seconds=span_seconds * i / (count + 1))
        nearest = min(commit_refs, key=lambda c: abs(datetime.fromisoformat(c.date) - target))
        picks.append(nearest)
    return picks


def select_checkpoints(commit_refs: list[CommitRef]) -> list[tuple[str, CommitRef]]:
    """Returns (label, CommitRef) pairs, chronological, oldest to "Today" --
    always real commits from `commit_refs`, and always distinctly labeled
    (a candidate whose label would collide with one already chosen is
    dropped, never shown as a second, confusingly-identical "Today" or "3
    weeks ago"). Prefers ~6/3/1-month-ago calendar points when the
    repository's own history spans enough real time for them to mean
    something; spreads checkpoints across the repository's own timespan
    otherwise -- never invents a date that doesn't correspond to a real
    commit."""
    if not commit_refs:
        return []
    if len(commit_refs) == 1:
        return [("Today", commit_refs[0])]

    earliest, head = commit_refs[0], commit_refs[-1]
    head_date = datetime.fromisoformat(head.date)
    earliest_date = datetime.fromisoformat(earliest.date)

    def label_for(ref: CommitRef) -> str:
        if ref.hash == head.hash:
            return "Today"
        return _relative_label(datetime.fromisoformat(ref.date), head_date)

    span_days = (head_date - earliest_date).days
    if span_days >= MIN_CALENDAR_SPAN_DAYS:
        candidates = _pick_calendar_checkpoints(commit_refs, head_date, earliest_date)
    else:
        candidates = _pick_time_spread_checkpoints(commit_refs, head_date, earliest_date, MAX_MIDDLE_CHECKPOINTS)

    chosen: list[CommitRef] = [earliest]
    chosen_hashes = {earliest.hash}
    chosen_labels = {label_for(earliest)}

    for pick in candidates:
        if pick.hash in chosen_hashes or pick.hash == head.hash:
            continue
        pick_label = label_for(pick)
        if pick_label in chosen_labels:
            continue
        chosen.append(pick)
        chosen_hashes.add(pick.hash)
        chosen_labels.add(pick_label)

    if head.hash not in chosen_hashes:
        chosen.append(head)

    chosen.sort(key=lambda c: c.date)
    chosen = chosen[:MAX_CHECKPOINTS]

    return [(label_for(ref), ref) for ref in chosen]


# =====================================================================
# Per-checkpoint metrics -- the same deterministic reduction of a
# RelationshipIndex, whether it came from the live repository or a
# materialized historical one.
# =====================================================================

SNAPSHOT_ANALYSIS_VERSION = 1


def _module_for(path: str) -> str:
    segments = path.split("/")
    return segments[0] if len(segments) > 1 else path


@dataclass
class SnapshotMetrics:
    module_count: int
    relationship_count: int
    avg_connections: float
    cross_module_links: int
    files_analyzed: int


def _compute_snapshot_metrics(day2_files: list[dict], intelligence: dict) -> SnapshotMetrics:
    index = RelationshipIndex(intelligence)

    module_count = len({_module_for(entry["path"]) for entry in day2_files})
    relationship_count = len(index.file_edges)
    total_degree = sum(len(index.reverse(p)) + len(index.forward(p)) for p in index.file_paths)
    avg_connections = (total_degree / len(index.file_paths)) if index.file_paths else 0.0
    cross_module_links = sum(
        1 for (source, target, _edge_type) in index.file_edges if _module_for(source) != _module_for(target)
    )

    return SnapshotMetrics(
        module_count=module_count,
        relationship_count=relationship_count,
        avg_connections=avg_connections,
        cross_module_links=cross_module_links,
        files_analyzed=len(day2_files),
    )


# Keyed on (repository path, commit SHA, analysis version): a commit's tree
# is immutable, so once a checkpoint is analyzed it is reused forever for
# that repository -- never recomputed on a later request, never mixed up
# with a different repository at the same path (repository_path is unique
# per import) or a different analysis methodology (SNAPSHOT_ANALYSIS_VERSION
# changes if the metric definitions above ever do).
_historical_snapshot_cache: dict[tuple[str, str, int], SnapshotMetrics | None] = {}


def _get_historical_snapshot(repository_path: Path, commit_hash: str) -> SnapshotMetrics | None:
    cache_key = (str(repository_path), commit_hash, SNAPSHOT_ANALYSIS_VERSION)
    if cache_key in _historical_snapshot_cache:
        return _historical_snapshot_cache[cache_key]

    snapshot: SnapshotMetrics | None = None
    with tempfile.TemporaryDirectory(prefix="codemap-drift-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        materialized = GitAnalyzer(repository_path).materialize_commit(commit_hash, temp_dir)
        if materialized:
            try:
                day2_result = RepositoryAnalyzer(temp_dir).analyze()
                intelligence = CodeIntelligenceAnalyzer(
                    temp_dir, day2_result, settings.max_parseable_file_size_bytes
                ).analyze()
                snapshot = _compute_snapshot_metrics(day2_result.files, intelligence.to_dict())
            except RepositoryAnalysisError:
                snapshot = None

    _historical_snapshot_cache[cache_key] = snapshot
    return snapshot


# =====================================================================
# Response models
# =====================================================================


class ArchitectureCheckpoint(BaseModel):
    label: str
    commit_hash: str
    commit_short_hash: str
    commit_date: str
    module_count: int
    relationship_count: int
    avg_connections: float
    cross_module_links: int
    files_analyzed: int


class ArchitectureDriftDelta(BaseModel):
    metric: str
    from_value: float
    to_value: float
    percent_change: float | None


class ArchitectureDriftResponse(BaseModel):
    has_git_history: bool
    has_enough_history: bool
    checkpoints: list[ArchitectureCheckpoint]
    deltas: list[ArchitectureDriftDelta]
    interpretation: str
    trend: str  # "more_interconnected" | "decoupling" | "proportional_growth" | "stable" | "not_enough_data"


# =====================================================================
# Interpretation -- deterministic, rule-based, never AI-generated. Never
# claims the architecture got "worse"; only characterizes how relationship
# growth compares to structural (module) growth.
# =====================================================================

STABLE_PERCENT_THRESHOLD = 5.0
INTERCONNECTION_RATIO = 1.3
DECOUPLING_RATIO = 0.7


def _pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / old * 100


def _interpret(first: ArchitectureCheckpoint, last: ArchitectureCheckpoint) -> tuple[str, str]:
    module_growth = _pct_change(first.module_count, last.module_count)
    relationship_growth = _pct_change(first.relationship_count, last.relationship_count)

    if module_growth is None:
        return "not_enough_data", "Not enough data to characterize architecture change over this period."

    if relationship_growth is None:
        # first.relationship_count was 0 -- a percentage change from zero is
        # undefined, but "0 relationships to N" is itself a real, meaningful
        # signal (or, if last is also 0, a real absence of one), not missing
        # data -- handled explicitly rather than folded into the ratio logic
        # below, which needs both growth rates to be defined.
        if last.relationship_count > 0:
            return "more_interconnected", (
                f"Dependency relationships went from 0 to {last.relationship_count} over this period "
                f"(module count changed {module_growth:+.0f}%) -- the codebase became interconnected where "
                f"it previously had no detected dependencies."
            )
        return "not_enough_data", (
            "No dependency relationships were detected at either checkpoint, so architectural "
            "interconnection can't be characterized for this period."
        )

    if abs(module_growth) < STABLE_PERCENT_THRESHOLD and abs(relationship_growth) < STABLE_PERCENT_THRESHOLD:
        return "stable", (
            f"Architecture has stayed stable over this period: module count changed {module_growth:+.0f}% "
            f"and dependency relationships changed {relationship_growth:+.0f}%."
        )

    if relationship_growth > 0 and relationship_growth > module_growth * INTERCONNECTION_RATIO:
        return "more_interconnected", (
            f"Dependency relationships increased {relationship_growth:.0f}% while module count increased "
            f"{module_growth:.0f}% over this period -- relationships grew faster than structure, so the "
            f"codebase has become more interconnected relative to its size."
        )

    if module_growth > 0 and relationship_growth < module_growth * DECOUPLING_RATIO:
        return "decoupling", (
            f"Module count increased {module_growth:.0f}% while dependency relationships increased only "
            f"{relationship_growth:.0f}% over this period -- the codebase has grown structurally without a "
            f"proportional rise in coupling."
        )

    return "proportional_growth", (
        f"Module count changed {module_growth:+.0f}% and dependency relationships changed "
        f"{relationship_growth:+.0f}% over this period -- growth without a clear shift toward more or less "
        f"interconnection."
    )


def _build_deltas(first: ArchitectureCheckpoint, last: ArchitectureCheckpoint) -> list[ArchitectureDriftDelta]:
    metrics = [
        ("modules", float(first.module_count), float(last.module_count)),
        ("relationships", float(first.relationship_count), float(last.relationship_count)),
        ("avg_connections", first.avg_connections, last.avg_connections),
        ("cross_module_links", float(first.cross_module_links), float(last.cross_module_links)),
    ]
    return [
        ArchitectureDriftDelta(metric=name, from_value=fv, to_value=tv, percent_change=_pct_change(fv, tv))
        for name, fv, tv in metrics
    ]


# =====================================================================
# Orchestration
# =====================================================================


def compute_architecture_drift(
    repository_path: Path, limit: int = MAX_DETAILED_HISTORY_LIMIT
) -> ArchitectureDriftResponse:
    git_analyzer = GitAnalyzer(repository_path)
    commit_refs = git_analyzer.commit_refs(limit)

    if not commit_refs:
        return ArchitectureDriftResponse(
            has_git_history=git_analyzer.available,
            has_enough_history=False,
            checkpoints=[],
            deltas=[],
            interpretation="No Git history available.",
            trend="not_enough_data",
        )

    selected = select_checkpoints(commit_refs)
    head_hash = commit_refs[-1].hash

    day2_result = get_repository_snapshot(repository_path)
    head_intelligence = get_or_build_code_intelligence(repository_path, day2_result)

    checkpoints: list[ArchitectureCheckpoint] = []
    for label, ref in selected:
        if ref.hash == head_hash:
            metrics = _compute_snapshot_metrics(day2_result.files, head_intelligence)
        else:
            metrics = _get_historical_snapshot(repository_path, ref.hash)

        if metrics is None:
            continue

        checkpoints.append(
            ArchitectureCheckpoint(
                label=label,
                commit_hash=ref.hash,
                commit_short_hash=ref.short_hash,
                commit_date=ref.date,
                module_count=metrics.module_count,
                relationship_count=metrics.relationship_count,
                avg_connections=round(metrics.avg_connections, 2),
                cross_module_links=metrics.cross_module_links,
                files_analyzed=metrics.files_analyzed,
            )
        )

    if len(checkpoints) < 2:
        return ArchitectureDriftResponse(
            has_git_history=True,
            has_enough_history=False,
            checkpoints=checkpoints,
            deltas=[],
            interpretation="Not enough historical checkpoints to measure architecture drift yet.",
            trend="not_enough_data",
        )

    first, last = checkpoints[0], checkpoints[-1]
    trend, interpretation = _interpret(first, last)

    return ArchitectureDriftResponse(
        has_git_history=True,
        has_enough_history=True,
        checkpoints=checkpoints,
        deltas=_build_deltas(first, last),
        interpretation=interpretation,
        trend=trend,
    )
