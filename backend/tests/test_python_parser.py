import pytest

from analyzer import LocalDependencyResolver, ParseError, PythonParser

SAMPLE = """from fastapi import FastAPI
from services.user import UserService

app = FastAPI()

def login():
    pass
"""


def _parse(tmp_path, source, filename="main.py"):
    file_path = tmp_path / filename
    file_path.write_text(source)
    return PythonParser().parse(file_path, filename)


def test_detects_imports(tmp_path):
    result = _parse(tmp_path, SAMPLE)
    sources = {imp.source for imp in result.imports}
    assert sources == {"fastapi", "services.user"}


def test_detects_function(tmp_path):
    result = _parse(tmp_path, SAMPLE)
    assert [fn.name for fn in result.functions] == ["login"]


def test_resolves_local_dependency():
    resolver = LocalDependencyResolver(["main.py", "services/user.py"])
    resolved = resolver.resolve_python("main.py", "services.user")
    assert resolved.target == "services/user.py"
    assert resolved.is_external is False


def test_detects_external_dependency():
    resolver = LocalDependencyResolver(["main.py"])
    resolved = resolver.resolve_python("main.py", "fastapi")
    assert resolved.is_external is True
    assert resolved.target is None


def test_resolves_explicit_relative_import():
    # One dot = same directory as the importing file.
    resolver = LocalDependencyResolver(["app/api/routes.py", "app/api/models.py"])
    resolved = resolver.resolve_python("app/api/routes.py", ".models")
    assert resolved.target == "app/api/models.py"

    # Two dots = parent directory.
    resolver = LocalDependencyResolver(["app/api/routes.py", "app/models.py"])
    resolved = resolver.resolve_python("app/api/routes.py", "..models")
    assert resolved.target == "app/models.py"


def test_absolute_import_prefers_shallower_file_on_collision():
    # A deeply nested test fixture happens to share a name with the real
    # top-level package -- the real package must win regardless of the
    # order paths were discovered in.
    resolver = LocalDependencyResolver(
        ["tests/fixtures/nested/deep/flask.py", "src/flask/__init__.py"]
    )
    resolved = resolver.resolve_python("tests/test_basic.py", "flask")
    assert resolved.target == "src/flask/__init__.py"


def test_class_and_methods_are_extracted(tmp_path):
    source = """class UserService:
    def create_user(self, name):
        self.validate(name)
        return name

    def validate(self, name):
        pass
"""
    result = _parse(tmp_path, source, "user_service.py")
    assert [cls.name for cls in result.classes] == ["UserService"]
    assert result.classes[0].methods == ["create_user", "validate"]
    method_names = {fn.name for fn in result.functions if fn.is_method}
    assert method_names == {"create_user", "validate"}


def test_fastapi_route_decorator_is_detected(tmp_path):
    source = '''@app.get("/users")
def get_users():
    pass
'''
    result = _parse(tmp_path, source, "routes.py")
    assert len(result.routes) == 1
    route = result.routes[0]
    assert route.method == "GET"
    assert route.path == "/users"
    assert route.handler == "get_users"


def test_malformed_syntax_does_not_raise(tmp_path):
    file_path = tmp_path / "broken.py"
    file_path.write_text("def broken(:\n    pass")
    result = PythonParser().parse(file_path, "broken.py")
    assert result.path == "broken.py"


def test_missing_file_raises_parse_error(tmp_path):
    with pytest.raises(ParseError):
        PythonParser().parse(tmp_path / "missing.py", "missing.py")
