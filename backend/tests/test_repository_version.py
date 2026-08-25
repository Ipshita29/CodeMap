from pathlib import Path

from git import Repo

from repository import get_repository_snapshot, repository_version


def _init_repo_with_commit(repo_path: Path, filename: str = "a.py", content: str = "x = 1\n") -> str:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (repo_path / filename).write_text(content)
    repo.index.add([filename])
    commit = repo.index.commit("initial commit")
    return commit.hexsha


def _commit(repo: Repo, filename: str, content: str, message: str) -> str:
    (Path(repo.working_dir) / filename).write_text(content)
    repo.index.add([filename])
    return repo.index.commit(message).hexsha


def test_repository_version_uses_the_commit_sha_for_a_git_repository(tmp_path):
    commit_hash = _init_repo_with_commit(tmp_path)
    assert repository_version(tmp_path) == commit_hash


def test_repository_version_changes_when_a_new_commit_lands(tmp_path):
    first_hash = _init_repo_with_commit(tmp_path)
    repo = Repo(tmp_path)
    second_hash = _commit(repo, "b.py", "y = 2\n", "second commit")

    assert first_hash != second_hash
    assert repository_version(tmp_path) == second_hash


def test_repository_version_is_stable_across_repeated_reads_of_the_same_commit(tmp_path):
    # A re-import that lands on the exact same commit (re-cloning the SAME
    # repository, not a fresh commit) must resolve to the same version
    # identity every time -- it must never depend on filesystem timestamps,
    # which a re-clone always changes even when the commit doesn't. See
    # test_answer_cache.py's equivalent cache-level regression test for the
    # user-visible behavior this protects.
    _init_repo_with_commit(tmp_path)

    first_read = repository_version(tmp_path)
    second_read = repository_version(tmp_path)

    assert first_read == second_read


def test_repository_version_falls_back_to_a_deterministic_value_for_non_git_directories(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    version = repository_version(tmp_path)

    assert version
    assert version == repository_version(tmp_path)


def test_snapshot_is_cached_and_deterministic_for_the_same_commit(tmp_path):
    _init_repo_with_commit(tmp_path)

    first = get_repository_snapshot(tmp_path)
    second = get_repository_snapshot(tmp_path)

    assert first is second  # served from the version-keyed cache
    assert first.repository_version == second.repository_version
    assert first.repository_version != ""


def test_snapshot_identity_and_contents_change_with_a_new_commit(tmp_path):
    _init_repo_with_commit(tmp_path)
    first = get_repository_snapshot(tmp_path)

    repo = Repo(tmp_path)
    _commit(repo, "b.py", "y = 2\n", "second commit")

    second = get_repository_snapshot(tmp_path)

    assert second.repository_version != first.repository_version
    assert second.total_files == first.total_files + 1


def test_snapshot_records_are_never_shared_across_different_repository_paths(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "only_in_a.py").write_text("x = 1\n")
    (repo_b / "only_in_b.py").write_text("y = 2\n")

    result_a = get_repository_snapshot(repo_a)
    result_b = get_repository_snapshot(repo_b)

    a_paths = {f["path"] for f in result_a.files}
    b_paths = {f["path"] for f in result_b.files}
    assert "only_in_a.py" in a_paths and "only_in_a.py" not in b_paths
    assert "only_in_b.py" in b_paths and "only_in_b.py" not in a_paths
