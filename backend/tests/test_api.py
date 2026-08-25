"""tests/test_api.py -- FastAPI integration tests.

Every other test file in this suite exercises repository.py/analyzer.py/
ai.py functions directly. This file is the missing layer: real HTTP
requests through main.app's actual routing, request validation, and
response-model serialization -- api.py's own wiring (repository_id
resolution, status-code translation, response construction) is what's
under test here, not the analysis logic underneath it.

The only thing ever stubbed is the actual external network boundary:
- the real `git clone` network call (GitService.clone_repository still
  runs for real -- only git.Repo.clone_from is redirected to create a
  real local repository instead of hitting GitHub), and
- the real outbound LLM call (ai_service.complete is the boundary AI.py
  itself is built around -- see its docstring -- so stubbing exactly that
  method exercises every layer above it -- context building from real
  repository data, prompt assembly, the answer cache, route wiring -- for
  real).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo

import ai
import main
import repository
from config import settings
from utils import AIRequestTimeoutError, AIServiceError

client = TestClient(main.app)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def isolated_clone_service(tmp_path, monkeypatch):
    """Points git_clone_service at a throwaway base_dir for the duration of
    the test, so imports here never touch the real cloned_repos/ directory
    or collide with other tests/sessions."""
    fake_service = repository.GitService(base_dir=tmp_path)
    monkeypatch.setattr(repository, "git_clone_service", fake_service)
    return fake_service


@pytest.fixture
def stub_clone(monkeypatch, isolated_clone_service):
    """Redirects git.Repo.clone_from to create a real local Git repository
    at the target path instead of performing a real network clone.
    GitService.clone_repository()'s own logic (the path-safety check, the
    rmtree-if-exists, the error translation) still runs unmodified -- only
    the actual network I/O is replaced."""

    def fake_clone_from(_url: str, target_path):
        target = Path(target_path)
        repo = Repo.init(target)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "Test User")
            cw.set_value("user", "email", "test@example.com")
        (target / "main.py").write_text("def handler():\n    return 'ok'\n")
        (target / "README.md").write_text("# Test repo\n")
        repo.index.add(["main.py", "README.md"])
        repo.index.commit("initial commit")

    monkeypatch.setattr(repository.Repo, "clone_from", staticmethod(fake_clone_from))


@pytest.fixture
def imported_repository(stub_clone):
    """Imports a repository through the real HTTP endpoint (exercising the
    full import route, not a shortcut) and returns its repository_id for
    tests that need an already-imported repository."""
    response = client.post("/repository/import", json={"github_url": "https://github.com/octocat/test-repo"})
    assert response.status_code == 200
    return response.json()["repository_name"]


@pytest.fixture
def stub_ai_complete(monkeypatch):
    """Stubs ai_service.complete -- the one real outbound LLM call -- to
    return a canned answer instead of hitting a live provider. Returns the
    call list so tests can assert on cache behavior (call count)."""
    calls = []

    def fake_complete(system_prompt: str, user_prompt: str) -> str:
        calls.append((system_prompt, user_prompt))
        return "This repository contains a simple handler function."

    monkeypatch.setattr(ai.ai_service, "complete", fake_complete)
    return calls


# =====================================================================
# Health check -- always 200 (liveness), status/component fields carry the
# readiness signal instead of the HTTP status code.
# =====================================================================


def test_health_check_reports_healthy_when_everything_is_fine(isolated_clone_service, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake-key-for-this-test")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "repository_storage": "ok", "ai_provider": "ok"}


def test_health_check_not_configured_ai_provider_does_not_degrade_status(isolated_clone_service, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_provider"] == "not_configured"
    assert body["status"] == "healthy"  # not configured is a valid state, not a failure


def test_health_check_reports_degraded_and_still_returns_200_when_storage_is_unwritable(
    isolated_clone_service, monkeypatch
):
    # A regular file standing in for base_dir -- writing a probe file
    # "inside" it fails deterministically (NotADirectoryError), regardless
    # of OS user/permissions, unlike a chmod-based approach.
    blocking_file = isolated_clone_service.base_dir.parent / "not_a_directory"
    blocking_file.write_text("x")
    monkeypatch.setattr(isolated_clone_service, "base_dir", blocking_file)

    response = client.get("/health")

    # The endpoint itself never fails -- an external/dependency problem
    # must never take the liveness signal down with it.
    assert response.status_code == 200
    body = response.json()
    assert body["repository_storage"] == "error"
    assert body["status"] == "degraded"


# =====================================================================
# Repository import
# =====================================================================


def test_import_repository_success_has_expected_response_structure(stub_clone):
    response = client.post("/repository/import", json={"github_url": "https://github.com/octocat/test-repo"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "repository_name": "test-repo",
        "clone_path": body["clone_path"],
        "status": "success",
    }
    assert body["clone_path"].endswith("test-repo")


def test_import_repository_malformed_url_is_400(isolated_clone_service):
    response = client.post("/repository/import", json={"github_url": "not-a-github-url"})

    assert response.status_code == 400
    assert "detail" in response.json()


def test_import_repository_missing_url_field_is_422(isolated_clone_service):
    response = client.post("/repository/import", json={})

    assert response.status_code == 422


# =====================================================================
# Repository not found -- no repository_id resolves without an import
# =====================================================================


@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/repository/analyze", {"repository_id": "ghost"}),
        ("GET", "/repository/tree", {"repository_id": "ghost"}),
        ("GET", "/repository/health", {"repository_id": "ghost"}),
        ("GET", "/repository/git/summary", {"repository_id": "ghost"}),
        ("GET", "/repository/chat/history", {"repository_id": "ghost"}),
    ],
)
def test_unimported_repository_id_is_404(isolated_clone_service, method, path, params):
    response = client.request(method, path, params=params)

    assert response.status_code == 404
    assert "detail" in response.json()


def test_chat_with_unimported_repository_id_is_404(isolated_clone_service):
    response = client.post(
        "/repository/chat", json={"repository_id": "ghost", "question": "What is this?", "mode": "beginner"}
    )

    assert response.status_code == 404


def test_impact_with_unimported_repository_id_is_404(isolated_clone_service):
    response = client.post("/repository/impact", json={"repository_id": "ghost", "file": "main.py"})

    assert response.status_code == 404


# =====================================================================
# Successful analysis routes, after a real import
# =====================================================================


def test_analyze_after_import_returns_real_repository_data(imported_repository):
    response = client.get("/repository/analyze", params={"repository_id": imported_repository})

    assert response.status_code == 200
    body = response.json()
    assert body["repository_name"] == "test-repo"
    assert body["total_files"] == 2  # main.py, README.md
    assert {f["path"] for f in body["files"]} == {"main.py", "README.md"}
    assert body["languages"].get("Python") == 1


def test_tree_after_import_agrees_with_analyze(imported_repository):
    analyze_body = client.get("/repository/analyze", params={"repository_id": imported_repository}).json()
    tree_body = client.get("/repository/tree", params={"repository_id": imported_repository}).json()

    assert tree_body["total_files"] == analyze_body["total_files"]
    assert tree_body["total_folders"] == analyze_body["total_folders"]


def test_health_after_import_returns_score_and_categories(imported_repository):
    response = client.get("/repository/health", params={"repository_id": imported_repository})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["score"], int)
    assert set(body["categories"].keys()) == {
        "structure",
        "dependencies",
        "complexity",
        "architecture",
        "documentation",
        "testing",
    }


def test_git_summary_after_import_reflects_the_real_commit(imported_repository):
    response = client.get("/repository/git/summary", params={"repository_id": imported_repository})

    assert response.status_code == 200
    body = response.json()
    assert body["has_git_history"] is True
    assert body["latest_commit"]["message"] == "initial commit"
    assert body["repository_contributors"] == 1


# =====================================================================
# Ask CodeMap / AI summary -- success (ai_service.complete stubbed)
# =====================================================================


def test_chat_success_returns_grounded_answer_and_expected_structure(imported_repository, stub_ai_complete):
    response = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "What does this repository do?", "mode": "beginner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "This repository contains a simple handler function."
    assert body["cached"] is False
    assert isinstance(body["sources"], list)
    assert body["mode"] == "beginner"
    assert len(stub_ai_complete) == 1


def test_chat_repeated_question_is_served_from_cache_without_a_second_ai_call(imported_repository, stub_ai_complete):
    first = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "How does the handler work?", "mode": "developer"},
    )
    second = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "How does the handler work?", "mode": "developer"},
    )

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["answer"] == first.json()["answer"]
    assert len(stub_ai_complete) == 1  # the AI was only ever called once


def test_summary_success_returns_both_modes(imported_repository, stub_ai_complete):
    response = client.post("/repository/summary", params={"repository_id": imported_repository})

    assert response.status_code == 200
    body = response.json()
    assert body["repository_name"] == "test-repo"
    assert body["beginner_summary"] == "This repository contains a simple handler function."
    assert body["developer_summary"] == "This repository contains a simple handler function."
    assert len(stub_ai_complete) == 2  # one completion per mode


# =====================================================================
# AI failure translation -- 503 (not configured), 504 (timeout), 502 (other)
# =====================================================================


def test_chat_ai_not_configured_returns_503(imported_repository, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    response = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "A brand new question nobody asked yet", "mode": "beginner"},
    )

    assert response.status_code == 503


def test_chat_ai_timeout_returns_504(imported_repository, monkeypatch):
    def raise_timeout(_system_prompt, _user_prompt):
        raise AIRequestTimeoutError("The AI request timed out. Please try again.")

    monkeypatch.setattr(ai.ai_service, "complete", raise_timeout)

    response = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "Yet another unique question", "mode": "beginner"},
    )

    assert response.status_code == 504


def test_chat_generic_ai_failure_returns_502(imported_repository, monkeypatch):
    def raise_generic(_system_prompt, _user_prompt):
        raise AIServiceError("The AI service returned an error. Please try again.")

    monkeypatch.setattr(ai.ai_service, "complete", raise_generic)

    response = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "Still another unique question", "mode": "beginner"},
    )

    assert response.status_code == 502


def test_summary_ai_not_configured_returns_503(imported_repository, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    response = client.post("/repository/summary", params={"repository_id": imported_repository})

    assert response.status_code == 503


# =====================================================================
# Malformed requests -- pydantic-level validation (422)
# =====================================================================


def test_chat_missing_question_field_is_422(imported_repository):
    response = client.post("/repository/chat", json={"repository_id": imported_repository, "mode": "beginner"})

    assert response.status_code == 422


def test_chat_blank_question_is_422(imported_repository):
    response = client.post(
        "/repository/chat", json={"repository_id": imported_repository, "question": "   ", "mode": "beginner"}
    )

    assert response.status_code == 422


def test_chat_invalid_mode_is_422(imported_repository):
    response = client.post(
        "/repository/chat",
        json={"repository_id": imported_repository, "question": "What is this?", "mode": "expert"},
    )

    assert response.status_code == 422


def test_impact_missing_file_field_is_422(imported_repository):
    response = client.post("/repository/impact", json={"repository_id": imported_repository})

    assert response.status_code == 422


def test_analyze_missing_repository_id_is_422():
    response = client.get("/repository/analyze")

    assert response.status_code == 422
