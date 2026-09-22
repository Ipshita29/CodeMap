from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import Actor, Repo

import architecture_drift
from architecture_drift import compute_architecture_drift, select_checkpoints
from repository import GitAnalyzer


def _init_repo(repo_path: Path) -> Repo:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Default Author")
        cw.set_value("user", "email", "default@example.com")
    return repo


def _commit_at(repo: Repo, files: dict[str, str], message: str, when: datetime):
    for filename, content in files.items():
        path = Path(repo.working_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    repo.index.add(list(files.keys()))
    author = Actor("Default Author", "default@example.com")
    date_str = when.strftime("%Y-%m-%dT%H:%M:%S")
    return repo.index.commit(message, author=author, committer=author, author_date=date_str, commit_date=date_str)


# =====================================================================
# select_checkpoints -- always real commits, never invented dates
# =====================================================================


def test_select_checkpoints_returns_only_today_for_a_single_commit():
    from repository import CommitRef

    only = CommitRef(hash="abc", short_hash="abc", date="2026-01-01T00:00:00+00:00", message="only commit")

    checkpoints = select_checkpoints([only])

    assert checkpoints == [("Today", only)]


def test_select_checkpoints_uses_real_commits_spanning_calendar_history(tmp_path):
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    _commit_at(repo, {"a.py": "1"}, "8 months ago", now - timedelta(days=240))
    _commit_at(repo, {"a.py": "2"}, "5 months ago", now - timedelta(days=150))
    _commit_at(repo, {"a.py": "3"}, "2 months ago", now - timedelta(days=60))
    _commit_at(repo, {"a.py": "4"}, "today", now)

    refs = GitAnalyzer(tmp_path).commit_refs(limit=50)
    checkpoints = select_checkpoints(refs)

    # Every checkpoint must be a real commit from `refs`.
    real_hashes = {r.hash for r in refs}
    assert all(ref.hash in real_hashes for _label, ref in checkpoints)
    # Chronological order, ending at the actual HEAD commit.
    dates = [ref.date for _label, ref in checkpoints]
    assert dates == sorted(dates)
    assert checkpoints[-1][1].hash == refs[-1].hash
    assert checkpoints[-1][0] == "Today"


def test_select_checkpoints_falls_back_to_time_spread_for_a_short_lived_repo(tmp_path):
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    for i in range(6):
        _commit_at(repo, {"a.py": str(i)}, f"commit {i}", now - timedelta(minutes=(5 - i)))

    refs = GitAnalyzer(tmp_path).commit_refs(limit=50)
    checkpoints = select_checkpoints(refs)

    real_hashes = {r.hash for r in refs}
    assert all(ref.hash in real_hashes for _label, ref in checkpoints)
    assert len(checkpoints) >= 2
    assert checkpoints[-1][1].hash == refs[-1].hash


def test_select_checkpoints_never_returns_duplicate_labels(tmp_path):
    # Regression: a repository whose entire history sits within a single
    # day (a burst of commits) must never produce two checkpoints both
    # labeled "Today" -- every returned label must be unique.
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    for i in range(10):
        _commit_at(repo, {"a.py": str(i)}, f"commit {i}", now - timedelta(hours=(9 - i)))

    refs = GitAnalyzer(tmp_path).commit_refs(limit=50)
    checkpoints = select_checkpoints(refs)

    labels = [label for label, _ref in checkpoints]
    assert len(labels) == len(set(labels))


def test_select_checkpoints_never_returns_duplicate_labels_for_a_mature_repo_with_a_burst(tmp_path):
    # A repository with real multi-month history AND a burst of same-day
    # commits near a calendar checkpoint (e.g. two commits both ~3 weeks
    # ago, minutes apart) must not surface both under the same label.
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    _commit_at(repo, {"a.py": "1"}, "start", now - timedelta(days=200))
    _commit_at(repo, {"a.py": "2"}, "burst 1", now - timedelta(days=21))
    _commit_at(repo, {"a.py": "3"}, "burst 2", now - timedelta(days=21, minutes=-29))
    _commit_at(repo, {"a.py": "4"}, "today", now)

    refs = GitAnalyzer(tmp_path).commit_refs(limit=50)
    checkpoints = select_checkpoints(refs)

    labels = [label for label, _ref in checkpoints]
    assert len(labels) == len(set(labels))


# =====================================================================
# compute_architecture_drift -- end to end against real materialized
# historical commits.
# =====================================================================


def test_drift_reports_not_enough_history_for_a_single_commit(tmp_path):
    repo = _init_repo(tmp_path)
    _commit_at(repo, {"a.py": "x = 1\n"}, "only commit", datetime.now(timezone.utc))

    result = compute_architecture_drift(tmp_path)

    assert result.has_git_history is True
    assert result.has_enough_history is False
    assert result.trend == "not_enough_data"


def test_drift_reports_no_git_history_for_non_git_directory(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    result = compute_architecture_drift(tmp_path)

    assert result.has_git_history is False
    assert result.has_enough_history is False


def test_drift_measures_real_growth_in_modules_and_relationships(tmp_path):
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)

    _commit_at(repo, {"a/one.py": "x = 1\n"}, "start small", now - timedelta(days=200))
    _commit_at(
        repo,
        {
            "a/one.py": "from b.two import helper\n\n\ndef use():\n    helper()\n",
            "b/two.py": "def helper():\n    pass\n",
            "c/three.py": "z = 1\n",
        },
        "grow the codebase",
        now,
    )

    result = compute_architecture_drift(tmp_path)

    assert result.has_git_history is True
    assert result.has_enough_history is True
    assert len(result.checkpoints) >= 2

    first, last = result.checkpoints[0], result.checkpoints[-1]
    # Real growth: 1 module -> 3 modules, 0 relationships -> at least 1.
    assert first.module_count == 1
    assert last.module_count == 3
    assert last.relationship_count >= first.relationship_count

    delta_by_metric = {d.metric: d for d in result.deltas}
    assert delta_by_metric["modules"].from_value == 1
    assert delta_by_metric["modules"].to_value == 3
    assert delta_by_metric["modules"].percent_change == 200.0

    assert result.trend in {"more_interconnected", "proportional_growth", "decoupling", "stable"}
    assert isinstance(result.interpretation, str) and len(result.interpretation) > 0


def test_drift_historical_snapshot_is_cached_and_not_recomputed(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    _commit_at(repo, {"a.py": "x = 1\n"}, "first", now - timedelta(days=200))
    _commit_at(repo, {"a.py": "x = 2\n", "b.py": "y = 1\n"}, "second", now)

    architecture_drift._historical_snapshot_cache.clear()
    compute_architecture_drift(tmp_path)

    call_count = 0
    original = GitAnalyzer.materialize_commit

    def counting_materialize(self, commit_hash, target_dir):
        nonlocal call_count
        call_count += 1
        return original(self, commit_hash, target_dir)

    monkeypatch.setattr(GitAnalyzer, "materialize_commit", counting_materialize)
    compute_architecture_drift(tmp_path)

    assert call_count == 0  # every historical checkpoint was already cached


def test_drift_does_not_mix_current_and_historical_repository_states(tmp_path):
    repo = _init_repo(tmp_path)
    now = datetime.now(timezone.utc)
    _commit_at(repo, {"a.py": "x = 1\n"}, "first", now - timedelta(days=200))
    _commit_at(repo, {"a.py": "x = 2\n", "b.py": "y = 1\n", "c.py": "z = 1\n"}, "second", now)

    result = compute_architecture_drift(tmp_path)

    first, last = result.checkpoints[0], result.checkpoints[-1]
    # The first checkpoint (a real historical commit) must reflect only
    # a.py -- not today's 3-file state leaking into an earlier snapshot.
    assert first.files_analyzed == 1
    assert last.files_analyzed == 3
