from pathlib import Path

from git import Actor, Repo

from evolution import (
    AI,
    BACKEND,
    DEPENDENCIES,
    DOCUMENTATION,
    FRONTEND,
    MULTI_AREA,
    OTHER,
    REPOSITORY_ANALYSIS,
    TESTING,
    build_evolution_timeline,
    classify_file,
)


def _init_repo(repo_path: Path) -> Repo:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Default Author")
        cw.set_value("user", "email", "default@example.com")
    return repo


def _commit(repo: Repo, files: dict[str, str], message: str, author: Actor | None = None):
    for filename, content in files.items():
        path = Path(repo.working_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    repo.index.add(list(files.keys()))
    return repo.index.commit(message, author=author) if author else repo.index.commit(message)


# =====================================================================
# classify_file -- deterministic path/extension/directory rules
# =====================================================================


def test_classify_file_recognizes_frontend_paths():
    assert classify_file("frontend/src/pages/overview.jsx") == FRONTEND
    assert classify_file("client/App.css") == FRONTEND


def test_classify_file_recognizes_backend_paths():
    assert classify_file("backend/main.py") == BACKEND
    assert classify_file("server/routes.go") == BACKEND


def test_classify_file_recognizes_ai_files():
    assert classify_file("backend/ai.py") == AI
    assert classify_file("backend/llm/prompt_builder.py") == AI


def test_classify_file_does_not_false_positive_on_ai_substring():
    # "aiport" contains "ai" as a substring but is not the whole filename
    # stem token "ai" -- must not be misclassified.
    assert classify_file("backend/aiport_config.py") != AI


def test_classify_file_recognizes_repository_analysis_files():
    assert classify_file("backend/analyzer.py") == REPOSITORY_ANALYSIS
    assert classify_file("backend/repository.py") != AI  # sanity: not misrouted to AI


def test_classify_file_recognizes_dependency_manifests():
    assert classify_file("frontend/package.json") == DEPENDENCIES
    assert classify_file("backend/requirements.txt") == DEPENDENCIES
    assert classify_file("package-lock.json") == DEPENDENCIES


def test_classify_file_recognizes_test_files():
    assert classify_file("backend/tests/test_api.py") == TESTING
    assert classify_file("frontend/src/App.test.jsx") == TESTING


def test_classify_file_recognizes_documentation():
    assert classify_file("README.md") == DOCUMENTATION
    assert classify_file("docs/architecture.md") == DOCUMENTATION


def test_classify_file_falls_back_to_other_for_unrecognized_paths():
    assert classify_file("LICENSE") != OTHER  # matched by doc filenames
    assert classify_file(".github/workflows/ci.yml") == OTHER


# =====================================================================
# build_evolution_timeline -- classify + group, end to end on a real repo
# =====================================================================


def test_evolution_timeline_groups_commits_by_area(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, {"backend/api.py": "x = 1\n"}, "add backend route")
    _commit(repo, {"backend/repository.py": "y = 2\n"}, "extend backend logic")
    _commit(repo, {"frontend/src/App.jsx": "export default function App() {}\n"}, "add frontend component")

    result = build_evolution_timeline(tmp_path)

    assert result.has_git_history is True
    assert result.analyzed_commit_count == 3
    areas = {area.area for area in result.areas}
    assert BACKEND in areas
    assert FRONTEND in areas


def test_evolution_timeline_marks_mixed_commits_as_multi_area(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        {"backend/api.py": "x = 1\n", "frontend/src/App.jsx": "export default function App() {}\n"},
        "wire up frontend to new backend route",
    )

    result = build_evolution_timeline(tmp_path)

    assert len(result.areas) == 1
    assert result.areas[0].area == MULTI_AREA
    assert result.areas[0].area_breakdown == {BACKEND: 1, FRONTEND: 1}


def test_evolution_timeline_orders_areas_newest_period_first(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, {"backend/api.py": "x = 1\n"}, "first: backend work")
    _commit(repo, {"frontend/src/App.jsx": "x\n"}, "second: frontend work")

    result = build_evolution_timeline(tmp_path)

    assert [area.area for area in result.areas] == [FRONTEND, BACKEND]


def test_evolution_timeline_evidence_includes_real_commit_data(tmp_path):
    repo = _init_repo(tmp_path)
    commit = _commit(repo, {"backend/api.py": "x = 1\n"}, "add backend route", Actor("Dev One", "dev@example.com"))

    result = build_evolution_timeline(tmp_path)

    assert len(result.areas) == 1
    evidence = result.areas[0].commits[0]
    assert evidence.hash == commit.hexsha
    assert evidence.author == "Dev One"
    assert evidence.files == ["backend/api.py"]


def test_evolution_timeline_reports_no_git_history_for_non_git_directory(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    result = build_evolution_timeline(tmp_path)

    assert result.has_git_history is False
    assert result.areas == []
