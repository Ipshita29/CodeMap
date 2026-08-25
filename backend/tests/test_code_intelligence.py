from pathlib import Path

from analyzer import CodeIntelligenceAnalyzer
from repository import RepositoryAnalyzer


def _build_repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "from services import login\n\n"
        "def handler():\n"
        "    login()\n"
        "    unknown_thing()\n"
    )
    (tmp_path / "services.py").write_text("def login():\n    pass\n")
    return tmp_path


def test_code_intelligence_resolves_imports_and_calls(tmp_path):
    repo_path = _build_repo(tmp_path)
    day2_result = RepositoryAnalyzer(repo_path).analyze()
    result = CodeIntelligenceAnalyzer(repo_path, day2_result, max_file_size_bytes=500_000).analyze()

    assert result.stats.files_parsed == 2
    assert result.stats.parse_errors == 0

    import_relationships = [r for r in result.relationships if r.type == "imports"]
    assert any(r.source == "app.py" and r.target == "services.py" for r in import_relationships)

    call_relationships = [r for r in result.relationships if r.type == "calls"]
    resolved = [r for r in call_relationships if r.resolved]
    unresolved = [r for r in call_relationships if not r.resolved]

    assert any(r.source == "app.py::handler" and r.target == "services.py::login" for r in resolved)
    assert any(r.raw_callee == "unknown_thing" for r in unresolved)


def test_oversized_file_is_skipped_not_errored(tmp_path):
    (tmp_path / "huge.py").write_text("x = 1\n" * 10)
    day2_result = RepositoryAnalyzer(tmp_path).analyze()
    result = CodeIntelligenceAnalyzer(tmp_path, day2_result, max_file_size_bytes=5).analyze()

    assert result.stats.files_skipped == 1
    assert result.stats.files_parsed == 0
    assert result.stats.parse_errors == 0


def _file_part(qualified_or_path: str) -> str:
    """"a.py::func" -> "a.py"; "a.py" -> "a.py"."""
    return qualified_or_path.split("::", 1)[0]


def test_symbols_and_relationships_are_grounded_in_files_that_actually_exist(tmp_path):
    # Regression guard: code intelligence must never report a symbol,
    # import, or relationship pointing at a file the repository scan
    # didn't actually find (a fabricated or stale path).
    repo_path = _build_repo(tmp_path)
    day2_result = RepositoryAnalyzer(repo_path).analyze()
    result = CodeIntelligenceAnalyzer(repo_path, day2_result, max_file_size_bytes=500_000).analyze()

    real_paths = {f["path"] for f in day2_result.files}
    assert real_paths  # sanity: the fixture actually produced scanned files

    for symbol in result.symbols:
        assert symbol.file in real_paths, f"symbol reports nonexistent file {symbol.file}"

    for imp in result.imports:
        assert imp.file in real_paths
        if imp.resolved_target is not None:
            assert imp.resolved_target in real_paths, f"import resolves to nonexistent file {imp.resolved_target}"

    for relationship in result.relationships:
        assert _file_part(relationship.source) in real_paths, (
            f"relationship source {relationship.source} is not a real file"
        )
        if relationship.resolved and relationship.target is not None:
            assert _file_part(relationship.target) in real_paths, (
                f"resolved relationship target {relationship.target} is not a real file"
            )
