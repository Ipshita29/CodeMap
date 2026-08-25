from pathlib import Path

from ai import RepositoryContextBuilder, _extract_keywords, _fuzzy_match
from analyzer import run_and_store_code_intelligence
from repository import RepositoryAnalyzer


def _build_auth_repo(tmp_path: Path) -> Path:
    (tmp_path / "authController.py").write_text(
        "from userService import create_user\n\n"
        "def login(email, password):\n"
        "    return create_user(email)\n"
    )
    (tmp_path / "userService.py").write_text("def create_user(email):\n    pass\n")
    (tmp_path / "homepage.py").write_text("def render_homepage():\n    pass\n")
    return tmp_path


def _build_context_builder(tmp_path) -> RepositoryContextBuilder:
    repo_path = _build_auth_repo(tmp_path)
    day2_result = RepositoryAnalyzer(repo_path).analyze()
    intelligence = run_and_store_code_intelligence(repo_path, day2_result).to_dict()
    return RepositoryContextBuilder(repo_path, day2_result, intelligence)


def test_extract_keywords_filters_stopwords_and_short_words():
    assert _extract_keywords("How does authentication work?") == ["authentication"]
    assert _extract_keywords("What is this repository about?") == []


def test_fuzzy_match_prefix_and_substring():
    assert _fuzzy_match("authentication", "authController.py")
    assert _fuzzy_match("login", "login")
    assert not _fuzzy_match("database", "authController.py")


def test_finds_relevant_file_via_symbol_name(tmp_path):
    # "login" isn't in the filename authController.py, but it IS a function
    # defined there -- this proves symbol matching, not just path matching.
    builder = _build_context_builder(tmp_path)
    relevant = builder.find_relevant_files("How does login work?")
    assert "authController.py" in relevant
    assert "homepage.py" not in relevant


def test_expands_relevant_files_via_import_relationship(tmp_path):
    # userService.py has no keyword match of its own, but authController.py
    # (which does match) imports it -- relationship expansion should pull
    # it in, same as the spec's User.js example for an auth question.
    builder = _build_context_builder(tmp_path)
    relevant = builder.find_relevant_files("How does login work?")
    assert "userService.py" in relevant


def test_build_context_includes_matched_source_and_sources_list(tmp_path):
    builder = _build_context_builder(tmp_path)
    context = builder.build_context("How does login work?")
    assert "authController.py" in context.sources
    assert "def login" in context.system_context


def test_build_context_falls_back_to_overview_with_no_keyword_matches(tmp_path):
    builder = _build_context_builder(tmp_path)
    context = builder.build_context("zzqxpv nonsense")
    assert context.sources == []
    assert "Repository metadata" in context.system_context
    assert "Code intelligence summary" in context.system_context


def test_context_sources_are_always_real_repository_files(tmp_path):
    # Regression guard for AI grounding: every source cited in an answer's
    # context must correspond to a file the canonical snapshot actually
    # found -- never a fabricated or stale path.
    builder = _build_context_builder(tmp_path)
    real_paths = {f["path"] for f in builder.day2_result.files}

    context = builder.build_context("How does login work?")

    assert context.sources, "expected at least one source for a matched question"
    assert set(context.sources) <= real_paths


def test_large_file_extracts_matching_symbol_only(tmp_path):
    repo_path = tmp_path
    padding = "\n".join(f"# padding line {i}" for i in range(500))
    (repo_path / "big.py").write_text(
        f"{padding}\n\ndef checkout(cart):\n    return cart\n\n{padding}\n"
    )
    day2_result = RepositoryAnalyzer(repo_path).analyze()
    intelligence = run_and_store_code_intelligence(repo_path, day2_result).to_dict()
    builder = RepositoryContextBuilder(repo_path, day2_result, intelligence)

    source = builder._read_source_section("big.py", ["checkout"])
    assert source is not None
    assert "def checkout" in source
    assert "padding line 0" not in source
