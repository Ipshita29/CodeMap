from pathlib import Path

from git import Repo

from hotspots import compute_hotspots


def _init_repo(repo_path: Path) -> Repo:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Default Author")
        cw.set_value("user", "email", "default@example.com")
    return repo


def _commit(repo: Repo, files: dict[str, str], message: str):
    for filename, content in files.items():
        (Path(repo.working_dir) / filename).write_text(content)
    repo.index.add(list(files.keys()))
    return repo.index.commit(message)


def test_frequently_changed_highly_connected_file_scores_higher_than_a_quiet_one(tmp_path):
    repo = _init_repo(tmp_path)
    # services.py: many commits, and app.py depends on it -- should be the hotspot.
    for i in range(6):
        _commit(repo, {"services.py": f"def login():\n    return {i}\n"}, f"update services #{i}")
    _commit(repo, {"app.py": "from services import login\n\n\ndef handler():\n    login()\n"}, "add app")
    # quiet.py: touched once, isolated, never depended on.
    _commit(repo, {"quiet.py": "x = 1\n"}, "add quiet module")

    result = compute_hotspots(tmp_path)

    assert result.has_git_history is True
    paths = [h.path for h in result.hotspots]
    assert "services.py" in paths
    services = next(h for h in result.hotspots if h.path == "services.py")
    quiet = next((h for h in result.hotspots if h.path == "quiet.py"), None)

    assert services.total_commits == 6
    assert services.direct_dependents >= 1
    assert services.score > (quiet.score if quiet else 0)
    assert "commit" in services.why.lower() or "connected" in services.why.lower()


def test_hotspot_excludes_files_deleted_since(tmp_path):
    repo = _init_repo(tmp_path)
    for i in range(5):
        _commit(repo, {"gone.py": f"x = {i}\n"}, f"update gone #{i}")
    (Path(repo.working_dir) / "gone.py").unlink()
    repo.index.remove(["gone.py"])
    repo.index.commit("remove gone.py")
    _commit(repo, {"present.py": "y = 1\n"}, "add present")

    result = compute_hotspots(tmp_path)

    paths = [h.path for h in result.hotspots]
    assert "gone.py" not in paths


def test_hotspot_evidence_is_traceable_to_real_commits(tmp_path):
    repo = _init_repo(tmp_path)
    commits = [_commit(repo, {"a.py": f"x = {i}\n"}, f"change a #{i}") for i in range(3)]

    result = compute_hotspots(tmp_path)

    a = next(h for h in result.hotspots if h.path == "a.py")
    assert a.total_commits == 3
    evidence_hashes = {c.short_hash for c in a.recent_commit_evidence}
    real_hashes = {c.hexsha[:7] for c in commits}
    assert evidence_hashes.issubset(real_hashes)
    assert "Calibrated against" in a.calibration_note


def test_hotspots_reports_no_git_history_for_non_git_directory(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    result = compute_hotspots(tmp_path)

    assert result.has_git_history is False
    assert result.hotspots == []


def test_hotspots_levels_are_valid(tmp_path):
    repo = _init_repo(tmp_path)
    for i in range(4):
        _commit(repo, {"a.py": f"x = {i}\n", "b.py": f"y = {i}\n"}, f"round {i}")

    result = compute_hotspots(tmp_path)

    for hotspot in result.hotspots:
        assert hotspot.level in {"low", "medium", "high"}
        assert 0 <= hotspot.score <= 100
