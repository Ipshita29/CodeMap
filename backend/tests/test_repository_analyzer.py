from pathlib import Path

from app.analyzer.repository_analyzer import RepositoryAnalyzer


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
