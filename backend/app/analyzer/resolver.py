import posixpath
from dataclasses import dataclass
from pathlib import Path

JS_RESOLVE_EXTENSIONS: list[str] = ["", ".js", ".jsx", ".ts", ".tsx"]


@dataclass
class ResolvedImport:
    target: str | None  # repo-relative path, if resolved
    is_external: bool


class LocalDependencyResolver:
    """Resolves an import's raw source string to a file already in the repo.

    Deliberately not a general-purpose module resolver (no package.json
    "exports" field, no tsconfig path aliases, no Python namespace packages)
    — per the Day 3 brief, the goal is reliable *local* resolution, with
    anything it can't confidently place falling back to "external" rather
    than a guess.
    """

    def __init__(self, all_paths: list[str]):
        self._all_paths: set[str] = set(all_paths)
        self._python_module_index = self._build_python_module_index(all_paths)

    def resolve_javascript(self, importing_file: str, raw_source: str) -> ResolvedImport:
        if not raw_source.startswith("."):
            return ResolvedImport(target=None, is_external=True)

        importing_dir = Path(importing_file).parent.as_posix()
        base = posixpath.normpath(posixpath.join(importing_dir, raw_source))

        if base in self._all_paths:
            return ResolvedImport(target=base, is_external=False)

        for extension in JS_RESOLVE_EXTENSIONS[1:]:
            candidate = f"{base}{extension}"
            if candidate in self._all_paths:
                return ResolvedImport(target=candidate, is_external=False)

        for extension in JS_RESOLVE_EXTENSIONS:
            candidate = f"{base}/index{extension}"
            if candidate in self._all_paths:
                return ResolvedImport(target=candidate, is_external=False)

        return ResolvedImport(target=None, is_external=False)  # relative but unresolved

    def resolve_python(self, importing_file: str, raw_source: str) -> ResolvedImport:
        if raw_source.startswith("."):
            return self._resolve_python_relative(importing_file, raw_source)
        return self._resolve_python_absolute(raw_source)

    def _resolve_python_relative(self, importing_file: str, raw_source: str) -> ResolvedImport:
        dot_count = len(raw_source) - len(raw_source.lstrip("."))
        remainder = raw_source[dot_count:]

        target_dir = Path(importing_file).parent
        for _ in range(dot_count - 1):
            target_dir = target_dir.parent

        if remainder:
            module_path = posixpath.join(target_dir.as_posix(), remainder.replace(".", "/"))
            for candidate in (f"{module_path}.py", f"{module_path}/__init__.py"):
                if candidate in self._all_paths:
                    return ResolvedImport(target=candidate, is_external=False)
            return ResolvedImport(target=None, is_external=False)

        return ResolvedImport(target=None, is_external=False)

    def _resolve_python_absolute(self, raw_source: str) -> ResolvedImport:
        target = self._python_module_index.get(raw_source)
        if target:
            return ResolvedImport(target=target, is_external=False)
        return ResolvedImport(target=None, is_external=True)

    def resolve_python_relative_name(self, importing_file: str, raw_source: str, name: str) -> ResolvedImport:
        """Resolve one name from `from . import name` / `from .. import name`,
        where the import statement's source has no module suffix of its own —
        the name itself is the submodule to locate."""
        dot_count = len(raw_source) - len(raw_source.lstrip("."))
        target_dir = Path(importing_file).parent
        for _ in range(dot_count - 1):
            target_dir = target_dir.parent

        module_path = posixpath.join(target_dir.as_posix(), name)
        for candidate in (f"{module_path}.py", f"{module_path}/__init__.py"):
            if candidate in self._all_paths:
                return ResolvedImport(target=candidate, is_external=False)
        return ResolvedImport(target=None, is_external=False)

    @staticmethod
    def _build_python_module_index(all_paths: list[str]) -> dict[str, str]:
        """Maps every dotted-suffix of each Python file's path to that file,
        e.g. backend/app/models/repository.py registers "repository",
        "models.repository", "app.models.repository", and
        "backend.app.models.repository" — so both a full absolute import and
        a src-layout-relative one (skipping the "backend" root) resolve.

        Files are processed shallowest-first so that on a suffix collision
        (e.g. a real top-level "flask" package vs. some deeply nested test
        fixture also named flask.py) the file closer to the repository root
        wins — that's almost always the actual package, not incidental
        fixture data.
        """
        index: dict[str, str] = {}
        for path in sorted(all_paths, key=lambda p: (p.count("/"), p)):
            posix_path = Path(path)
            if posix_path.suffix != ".py":
                continue

            parts = list(posix_path.parts[:-1])
            stem = posix_path.stem
            if stem != "__init__":
                parts.append(stem)
            if not parts:
                continue

            for start in range(len(parts)):
                suffix = ".".join(parts[start:])
                index.setdefault(suffix, path)
        return index
