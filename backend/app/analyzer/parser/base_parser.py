"""Shared data model and interface every language parser implements.

Keeping this contract independent of any specific Tree-sitter grammar is
what lets a new language be added later (parser/go_parser.py, etc.) without
touching CodeIntelligenceAnalyzer, the resolver, or the API layer — they
only ever see ParsedFile.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


def symbol_id(file: str, name: str) -> str:
    """Qualified identifier for a symbol, e.g. "src/App.jsx::App"."""
    return f"{file}::{name}"


@dataclass
class ImportInfo:
    file: str
    source: str
    imported_names: list[str] = field(default_factory=list)
    is_default: bool = False
    line: int = 0


@dataclass
class ExportInfo:
    file: str
    name: str
    kind: str  # "function" | "class" | "variable" | "default"
    line: int = 0


@dataclass
class FunctionInfo:
    name: str
    file: str
    start_line: int
    end_line: int
    parameters: list[str] = field(default_factory=list)
    is_method: bool = False
    class_name: str | None = None


@dataclass
class ClassInfo:
    name: str
    file: str
    start_line: int
    end_line: int
    methods: list[str] = field(default_factory=list)


@dataclass
class CallInfo:
    """A raw, unresolved call site as seen in the source.

    Resolution (deciding what `callee_raw` actually points to) is
    deliberately not this layer's job — see relationship building in
    code_intelligence.py, which only links a call when it can do so
    confidently and otherwise leaves it unresolved rather than guessing.
    """

    callee_raw: str
    is_member_call: bool
    line: int
    caller_name: str | None = None  # enclosing function/method name, if any
    caller_class: str | None = None  # enclosing class, if caller_name is a method


@dataclass
class RouteInfo:
    method: str
    path: str
    handler: str
    file: str
    line: int = 0


@dataclass
class ParsedFile:
    path: str
    language: str
    imports: list[ImportInfo] = field(default_factory=list)
    exports: list[ExportInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    routes: list[RouteInfo] = field(default_factory=list)


class ParseError(Exception):
    """Raised when a file cannot be parsed or read."""


class BaseParser(ABC):
    """Common interface every language parser implements.

    CodeIntelligenceAnalyzer and ParserFactory only depend on this
    interface, never on a concrete Tree-sitter grammar — that's what keeps
    the rest of CodeMap decoupled from any one parser implementation.
    """

    language_name: str

    @abstractmethod
    def parse(self, file_path: Path, relative_path: str) -> ParsedFile:
        """Parse a single source file and extract its structured elements.

        Raises ParseError if the file cannot be read or parsed; callers are
        expected to catch this per-file and continue with the rest of the
        repository.
        """
