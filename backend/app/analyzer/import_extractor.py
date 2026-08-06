import re

JS_EXTENSIONS: set[str] = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"}
PYTHON_EXTENSIONS: set[str] = {".py"}

# Matches `import X from "Y"`, `import "Y"`, `export ... from "Y"`, and
# `require("Y")`. Deliberately regex-based rather than AST/Tree-sitter based
# — good enough to seed a future dependency graph, not a correctness-critical
# parser.
_JS_IMPORT_PATTERN = re.compile(
    r"(?:import|export)\s+(?:[^'\"]*?\sfrom\s+)?['\"]([^'\"]+)['\"]"
    r"|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)

_PY_FROM_IMPORT_PATTERN = re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.MULTILINE)
_PY_IMPORT_PATTERN = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)


class ImportExtractor:
    """Best-effort import extraction for JS/TS and Python source text.

    Stores the *source* being imported from (module path / package name),
    not the local binding name — e.g. `import Navbar from "./Navbar"` yields
    "./Navbar", and `from fastapi import FastAPI` yields "fastapi". That's
    the shape a future dependency graph needs.
    """

    @classmethod
    def extract(cls, content: str, extension: str) -> list[str]:
        if extension in JS_EXTENSIONS:
            return cls._extract_js(content)
        if extension in PYTHON_EXTENSIONS:
            return cls._extract_python(content)
        return []

    @staticmethod
    def _extract_js(content: str) -> list[str]:
        imports: list[str] = []
        for match in _JS_IMPORT_PATTERN.finditer(content):
            source = match.group(1) or match.group(2)
            if source:
                imports.append(source)
        return imports

    @staticmethod
    def _extract_python(content: str) -> list[str]:
        imports: list[str] = []
        for match in _PY_FROM_IMPORT_PATTERN.finditer(content):
            imports.append(match.group(1))
        for match in _PY_IMPORT_PATTERN.finditer(content):
            imports.extend(name.strip() for name in match.group(1).split(","))
        return imports
