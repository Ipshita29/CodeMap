"""Regression tests for the repository_id fix: every repository-scoped route
must resolve strictly from the repository_id the client sends, never from
"whichever repository was imported/cloned most recently". Without this,
two repositories imported close together (e.g. two concurrent users) could
have one client's requests silently resolve to the other's data.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import repository

client = TestClient(main.app)


@pytest.fixture
def two_repositories(tmp_path, monkeypatch):
    """Two already-"imported" repositories with disjoint files, sitting
    side by side under a fresh base_dir -- standing in for two different
    users/sessions each having imported a different repository."""
    real_service = repository.git_clone_service
    fake_service = repository.GitService(base_dir=tmp_path)
    monkeypatch.setattr(repository, "git_clone_service", fake_service)

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a_only.py").write_text("x = 1\n")
    (repo_b / "b_only.py").write_text("y = 2\n")

    yield repo_a, repo_b

    monkeypatch.setattr(repository, "git_clone_service", real_service)


def test_analyze_returns_only_the_requested_repositorys_files(two_repositories):
    response_a = client.get("/repository/analyze", params={"repository_id": "repo_a"})
    response_b = client.get("/repository/analyze", params={"repository_id": "repo_b"})

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    paths_a = {f["path"] for f in response_a.json()["files"]}
    paths_b = {f["path"] for f in response_b.json()["files"]}

    assert "a_only.py" in paths_a and "b_only.py" not in paths_a
    assert "b_only.py" in paths_b and "a_only.py" not in paths_b


def test_tree_returns_only_the_requested_repositorys_files(two_repositories):
    def tree_paths(payload) -> set[str]:
        paths = set()

        def walk(nodes):
            for node in nodes:
                if node["type"] == "file":
                    paths.add(node["path"])
                elif node.get("children"):
                    walk(node["children"])

        walk(payload["tree"])
        return paths

    response_a = client.get("/repository/tree", params={"repository_id": "repo_a"})
    response_b = client.get("/repository/tree", params={"repository_id": "repo_b"})

    assert tree_paths(response_a.json()) == {"a_only.py"}
    assert tree_paths(response_b.json()) == {"b_only.py"}


def test_unknown_repository_id_is_a_404_not_a_silent_fallback(two_repositories):
    response = client.get("/repository/analyze", params={"repository_id": "does-not-exist"})

    assert response.status_code == 404


def test_repository_id_is_required_no_implicit_current_repository(two_repositories):
    # No query param at all -- FastAPI must reject this outright (422), never
    # silently fall back to "whichever repository is current".
    response = client.get("/repository/analyze")

    assert response.status_code == 422


def test_path_traversal_in_repository_id_is_rejected(two_repositories):
    response = client.get("/repository/analyze", params={"repository_id": "../../etc"})

    assert response.status_code == 404


def test_get_repository_path_rejects_traversal_outside_base_dir(tmp_path):
    service = repository.GitService(base_dir=tmp_path)
    (tmp_path / "real_repo").mkdir()

    with pytest.raises(repository.NoRepositoryImportedError):
        service.get_repository_path("../outside")
