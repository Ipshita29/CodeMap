from pathlib import Path

from repository import RepositoryAnalyzer


def _write(repo: Path, relative_path: str, content: str = "x = 1\n") -> None:
    full_path = repo / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


def _find(nodes, path_parts):
    for node in nodes:
        if node.name != path_parts[0]:
            continue
        if len(path_parts) == 1:
            return node
        if node.children is None:
            return None
        return _find(node.children, path_parts[1:])
    return None


def _count_nodes(nodes):
    files = directories = 0
    for node in nodes:
        if node.type == "file":
            files += 1
        else:
            directories += 1
            sub_files, sub_dirs = _count_nodes(node.children)
            files += sub_files
            directories += sub_dirs
    return files, directories


def test_nested_paths_are_preserved_as_a_real_hierarchy(tmp_path):
    _write(tmp_path, "src/flask/app.py")
    _write(tmp_path, "tests/test_basic.py")
    _write(tmp_path, "src/flask/test_basic.py")

    result = RepositoryAnalyzer(tmp_path).analyze()

    app_node = _find(result.repository_tree, ["src", "flask", "app.py"])
    assert app_node is not None
    assert app_node.type == "file"
    assert app_node.path == "src/flask/app.py"

    # Same basename in two different directories must remain two distinct files.
    root_test = _find(result.repository_tree, ["tests", "test_basic.py"])
    nested_test = _find(result.repository_tree, ["src", "flask", "test_basic.py"])
    assert root_test is not None and nested_test is not None
    assert root_test.path == "tests/test_basic.py"
    assert nested_test.path == "src/flask/test_basic.py"


def test_hidden_directories_and_files_are_preserved(tmp_path):
    _write(tmp_path, ".github/workflows/ci.yml", "name: ci\n")
    _write(tmp_path, ".editorconfig", "root = true\n")

    result = RepositoryAnalyzer(tmp_path).analyze()

    assert _find(result.repository_tree, [".editorconfig"]) is not None
    ci_node = _find(result.repository_tree, [".github", "workflows", "ci.yml"])
    assert ci_node is not None
    assert ci_node.path == ".github/workflows/ci.yml"


def test_ignored_directories_are_pruned_from_tree_and_counts(tmp_path):
    _write(tmp_path, "src/app.py")
    _write(tmp_path, "node_modules/some-package/index.js")

    result = RepositoryAnalyzer(tmp_path).analyze()

    assert _find(result.repository_tree, ["node_modules"]) is None
    assert result.total_files == 1
    assert all(f["path"] != "node_modules/some-package/index.js" for f in result.files)


def test_total_files_and_folders_match_the_canonical_tree_exactly(tmp_path):
    _write(tmp_path, "src/flask/app.py")
    _write(tmp_path, "src/flask/helpers.py")
    _write(tmp_path, "tests/test_basic.py")
    _write(tmp_path, "docs/index.md")
    _write(tmp_path, "README.md")

    result = RepositoryAnalyzer(tmp_path).analyze()

    tree_files, tree_dirs = _count_nodes(result.repository_tree)
    assert tree_files == result.total_files
    assert tree_dirs == result.total_folders
    # src, src/flask, tests, docs -- root itself is never counted as a folder.
    assert result.total_folders == 4
    assert result.total_files == 5


def _all_tree_paths(nodes, kind: str) -> list[str]:
    paths = []
    for node in nodes:
        if node.type == kind:
            paths.append(node.path)
        if node.children is not None:
            paths.extend(_all_tree_paths(node.children, kind))
    return paths


def test_every_reported_file_actually_exists_on_disk(tmp_path):
    # Regression guard for CodeMap.3 -- the canonical tree must never claim
    # a file that isn't actually there (fabricated/stale entries).
    _write(tmp_path, "src/flask/app.py")
    _write(tmp_path, "tests/test_basic.py")
    _write(tmp_path, "README.md")

    result = RepositoryAnalyzer(tmp_path).analyze()

    for path in _all_tree_paths(result.repository_tree, "file"):
        assert (tmp_path / path).is_file(), f"tree claims {path} exists but it does not"
    for record in result.files:
        assert (tmp_path / record["path"]).is_file()


def test_no_duplicate_file_paths_in_the_canonical_tree_or_file_list(tmp_path):
    _write(tmp_path, "src/flask/app.py")
    _write(tmp_path, "src/flask/helpers.py")
    _write(tmp_path, "tests/test_basic.py")

    result = RepositoryAnalyzer(tmp_path).analyze()

    tree_paths = _all_tree_paths(result.repository_tree, "file")
    assert len(tree_paths) == len(set(tree_paths))

    file_list_paths = [record["path"] for record in result.files]
    assert len(file_list_paths) == len(set(file_list_paths))


def test_repository_tree_omits_nothing_the_file_list_reports(tmp_path):
    _write(tmp_path, "src/flask/app.py")
    _write(tmp_path, "src/flask/helpers.py")
    _write(tmp_path, "tests/test_basic.py")
    _write(tmp_path, "docs/index.md")

    result = RepositoryAnalyzer(tmp_path).analyze()

    tree_paths = set(_all_tree_paths(result.repository_tree, "file"))
    file_list_paths = {record["path"] for record in result.files}
    assert tree_paths == file_list_paths


def test_language_percentages_reflect_actual_file_contents_not_guesses(tmp_path):
    _write(tmp_path, "src/app.py")
    _write(tmp_path, "src/helpers.py")
    _write(tmp_path, "src/main.js")
    _write(tmp_path, "README.md")

    result = RepositoryAnalyzer(tmp_path).analyze()

    # Every language present must be backed by at least one real file of
    # that language -- none of it is estimated or hard-coded.
    assert result.languages["Python"] == 2
    assert result.languages["JavaScript"] == 1
    assert sum(result.languages.values()) <= result.total_files
    assert "NotARealLanguage" not in result.languages
