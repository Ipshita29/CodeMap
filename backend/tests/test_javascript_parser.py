import pytest

from analyzer import JavaScriptParser, LocalDependencyResolver, ParseError

SAMPLE = """import axios from "axios";
import User from "./User";

export function login() {
    return axios.post("/login");
}
"""


def _parse(tmp_path, source, filename="auth.js"):
    file_path = tmp_path / filename
    file_path.write_text(source)
    return JavaScriptParser().parse(file_path, filename)


def test_detects_imports(tmp_path):
    result = _parse(tmp_path, SAMPLE)
    sources = {imp.source for imp in result.imports}
    assert sources == {"axios", "./User"}


def test_detects_function(tmp_path):
    result = _parse(tmp_path, SAMPLE)
    assert [fn.name for fn in result.functions] == ["login"]


def test_detects_export(tmp_path):
    result = _parse(tmp_path, SAMPLE)
    assert len(result.exports) == 1
    assert result.exports[0].name == "login"
    assert result.exports[0].kind == "function"


def test_resolves_local_dependency():
    resolver = LocalDependencyResolver(["auth.js", "User.js"])
    resolved = resolver.resolve_javascript("auth.js", "./User")
    assert resolved.target == "User.js"
    assert resolved.is_external is False


def test_detects_external_dependency():
    resolver = LocalDependencyResolver(["auth.js"])
    resolved = resolver.resolve_javascript("auth.js", "axios")
    assert resolved.is_external is True
    assert resolved.target is None


def test_resolves_directory_index_import():
    resolver = LocalDependencyResolver(["App.jsx", "components/Button/index.jsx"])
    resolved = resolver.resolve_javascript("App.jsx", "./components/Button")
    assert resolved.target == "components/Button/index.jsx"
    assert resolved.is_external is False


def test_unresolved_relative_import_is_not_marked_external():
    resolver = LocalDependencyResolver(["App.jsx"])
    resolved = resolver.resolve_javascript("App.jsx", "./DoesNotExist")
    assert resolved.target is None
    assert resolved.is_external is False


def test_class_and_methods_are_extracted(tmp_path):
    source = """export class UserService {
  createUser(name) {
    return name;
  }
  deleteUser() {}
}
"""
    result = _parse(tmp_path, source, "UserService.js")
    assert [cls.name for cls in result.classes] == ["UserService"]
    assert result.classes[0].methods == ["createUser", "deleteUser"]
    method_names = {fn.name for fn in result.functions if fn.is_method}
    assert method_names == {"createUser", "deleteUser"}


def test_express_route_is_detected(tmp_path):
    source = 'router.get("/users", getUsers);\n'
    result = _parse(tmp_path, source, "routes.js")
    assert len(result.routes) == 1
    route = result.routes[0]
    assert route.method == "GET"
    assert route.path == "/users"
    assert route.handler == "getUsers"


def test_malformed_syntax_does_not_raise(tmp_path):
    file_path = tmp_path / "broken.js"
    file_path.write_text("function( { [ unterminated")
    result = JavaScriptParser().parse(file_path, "broken.js")
    assert result.path == "broken.js"  # tree-sitter is error-tolerant; just extracts what it can


def test_missing_file_raises_parse_error(tmp_path):
    with pytest.raises(ParseError):
        JavaScriptParser().parse(tmp_path / "missing.js", "missing.js")
