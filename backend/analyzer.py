"""analyzer.py -- repository/code intelligence built on top of
repository.py's canonical snapshot: AST parsing, symbol/import/export
extraction, relationship analysis, architecture/dependency graph
construction, API/route-aware change-impact analysis, and repository health
scoring.

Nothing here re-scans the filesystem or re-derives file/folder/language
facts independently -- every analyzer in this file takes repository.py's
`AnalysisResult` (or the `CodeIntelligenceResult` built from it) as input.
Repository scanning, the file/folder tree, language detection, and the
canonical snapshot itself live in repository.py, not here -- see that
module's docstring for the (path, version)-keyed cache this file always
reads from rather than re-walking disk.

  repository.AnalysisResult (repository.py's canonical snapshot)
        |
        v
  CodeIntelligenceAnalyzer -> CodeIntelligenceResult (symbols, imports,
        |                      exports, routes, relationships)
        |
        +--> RelationshipIndex (shared file-level edges)
                |
                +--> GraphBuilder      (Architecture / Dependencies view)
                +--> ImpactAnalyzer    (change-impact BFS)
                +--> HealthAnalyzer    (structural health score)

Dependency direction: this file imports ai_service/IMPACT_EXPLANATION_PROMPT
from ai.py (used only by ImpactAnalyzer's optional AI-generated explanation,
section 11) -- but ai.py never imports anything from here. See ai.py's
module docstring for why that one-directional edge is deliberate.

Sections -- a developer looking for X should not need to read past its
section to find it:
  1.  Shared parsing primitives (BaseParser and the dataclasses every
      parser below returns: ImportInfo, ExportInfo, FunctionInfo, ClassInfo,
      CallInfo, RouteInfo, ParsedFile)
  2.  AST parsing -- Python (PythonParser)
  3.  AST parsing -- JavaScript (JavaScriptParser)
  4.  AST parsing -- TypeScript (TypeScriptParser, extends JavaScriptParser)
  5.  Parser factory / language dispatch (ParserFactory)
  6.  Import/export resolution -- raw import strings to actual local files
      (LocalDependencyResolver)
  7.  Code intelligence construction -- runs the right parser over every
      file and resolves symbols, imports, exports, routes, and
      call/import relationships into one CodeIntelligenceResult
      (CodeIntelligenceAnalyzer)
  8.  Analysis caching -- on-disk persistence of a CodeIntelligenceResult
      and the on-demand build service (AnalysisStorage,
      run_and_store_code_intelligence, get_or_build_code_intelligence)
  9.  Relationship analysis -- the shared file-level edge index every
      consumer below builds on (RelationshipIndex)
  10. Architecture/dependency graph construction (GraphBuilder,
      build_repository_graph)
  11. API/route detection + change-impact analysis -- matching HTTP client
      calls to parsed routes, and BFS-ing the relationship graph for a
      change's blast radius (extract_api_calls, match_route, ImpactAnalyzer,
      analyze_change_impact)
  12. Repository health analysis (HealthAnalyzer, analyze_repository_health)
  13. Public response models (code intelligence, graph, impact, health) +
      this module's public interface (see __all__ at the end of that
      section)
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from pydantic import BaseModel
from tree_sitter import Language, Node, Parser

from ai import IMPACT_EXPLANATION_PROMPT, ai_service
from config import settings
from repository import AnalysisResult, get_repository_snapshot, git_clone_service
from utils import AIRequestTimeoutError, AIServiceError, AIServiceNotConfiguredError

logger = logging.getLogger(__name__)


# =====================================================================
# 1. Shared parsing primitives
# =====================================================================


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
    deliberately not this layer's job — see relationship building below,
    which only links a call when it can do so confidently and otherwise
    leaves it unresolved rather than guessing.
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


# =====================================================================
# 2. AST parsing -- Python
# =====================================================================

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
ROUTE_DECORATOR_OBJECTS = {"app", "router"}


class PythonParser(BaseParser):
    """Tree-sitter-based extraction for Python.

    `is_method` is inferred purely from AST nesting — Python has no separate
    "method" node type, a method is just a function_definition inside a
    class_definition's block — mirrored via the same current_class threading
    JavaScriptParser uses for its class bodies.
    """

    language_name = "Python"

    def __init__(self):
        self._parser = Parser(Language(tspy.language()))

    def parse(self, file_path: Path, relative_path: str) -> ParsedFile:
        try:
            source = file_path.read_bytes()
        except OSError as exc:
            raise ParseError(str(exc)) from exc

        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            raise ParseError(str(exc)) from exc

        parsed = ParsedFile(path=relative_path, language=self.language_name)
        self._visit(tree.root_node, source, parsed, current_function=None, current_class=None)
        return parsed

    # -- traversal ---------------------------------------------------------

    def _visit(
        self,
        node: Node,
        source: bytes,
        parsed: ParsedFile,
        current_function: str | None,
        current_class: str | None,
    ) -> None:
        node_type = node.type
        child_function = current_function
        child_class = current_class

        if node_type == "import_statement":
            self._handle_import_statement(node, source, parsed)
        elif node_type == "import_from_statement":
            self._handle_import_from_statement(node, source, parsed)
        elif node_type == "assignment":
            self._handle_dunder_all(node, source, parsed)
        elif node_type == "call":
            self._handle_call(node, source, parsed, current_function, current_class)
        elif node_type == "decorated_definition":
            self._handle_decorated_definition(node, source, parsed)
        elif node_type == "class_definition":
            child_class = self._handle_class(node, source, parsed)
            child_function = None
        elif node_type == "function_definition":
            name = self._child_text(node, {"identifier"}, source)
            if name:
                parsed.functions.append(
                    FunctionInfo(
                        name=name,
                        file=parsed.path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parameters=self._extract_parameters(node, source),
                        is_method=current_class is not None,
                        class_name=current_class,
                    )
                )
                child_function = name

        for child in node.children:
            self._visit(child, source, parsed, child_function, child_class)

    # -- imports / exports ---------------------------------------------------

    def _handle_import_statement(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        """`import os` / `import os as o` / `import os, sys` — each module is
        an independent import, unlike `from x import a, b` below."""
        for child in node.children:
            if child.type == "dotted_name":
                text = self._node_text(child, source)
                parsed.imports.append(
                    ImportInfo(file=parsed.path, source=text, imported_names=[text], line=node.start_point[0] + 1)
                )
            elif child.type == "aliased_import":
                module = self._first_child_of_type(child, "dotted_name")
                ids = [c for c in child.children if c.type == "identifier"]
                if module is not None and ids:
                    parsed.imports.append(
                        ImportInfo(
                            file=parsed.path,
                            source=self._node_text(module, source),
                            imported_names=[self._node_text(ids[-1], source)],
                            line=node.start_point[0] + 1,
                        )
                    )

    def _handle_import_from_statement(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        """`from x import a, b` — all names share the same source module."""
        module_node = None
        for child in node.children:
            if child.type in ("dotted_name", "relative_import"):
                module_node = child
                break
        if module_node is None:
            return

        imported_names: list[str] = []
        for child in node.children:
            if child.type == "dotted_name" and child is not module_node:
                imported_names.append(self._node_text(child, source))
            elif child.type == "aliased_import":
                ids = [c for c in child.children if c.type == "identifier"]
                if ids:
                    imported_names.append(self._node_text(ids[-1], source))
            elif child.type == "wildcard_import":
                imported_names.append("*")

        parsed.imports.append(
            ImportInfo(
                file=parsed.path,
                source=self._node_text(module_node, source),
                imported_names=imported_names,
                line=node.start_point[0] + 1,
            )
        )

    def _handle_dunder_all(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        if len(node.children) < 2:
            return
        left, right = node.children[0], node.children[-1]
        if left.type != "identifier" or self._node_text(left, source) != "__all__":
            return
        if right.type not in ("list", "tuple"):
            return
        for child in right.children:
            if child.type == "string":
                name = self._string_literal_text(child, source)
                if name:
                    parsed.exports.append(
                        ExportInfo(file=parsed.path, name=name, kind="variable", line=node.start_point[0] + 1)
                    )

    # -- functions / classes -------------------------------------------------

    def _handle_class(self, node: Node, source: bytes, parsed: ParsedFile) -> str | None:
        name = self._child_text(node, {"identifier"}, source)
        if not name:
            return None

        block = self._first_child_of_type(node, "block")
        methods = self._direct_method_names(block, source) if block is not None else []

        parsed.classes.append(
            ClassInfo(
                name=name,
                file=parsed.path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                methods=methods,
            )
        )
        return name

    def _direct_method_names(self, block: Node, source: bytes) -> list[str]:
        names: list[str] = []
        for child in block.children:
            func_def = None
            if child.type == "function_definition":
                func_def = child
            elif child.type == "decorated_definition":
                func_def = self._first_child_of_type(child, "function_definition")
            if func_def is not None:
                name = self._child_text(func_def, {"identifier"}, source)
                if name:
                    names.append(name)
        return names

    def _extract_parameters(self, func_node: Node, source: bytes) -> list[str]:
        params_node = self._first_child_of_type(func_node, "parameters")
        if params_node is None:
            return []
        names: list[str] = []
        for child in params_node.children:
            if child.type in ("(", ")", ","):
                continue
            names.append(self._parameter_name(child, source))
        return names

    def _parameter_name(self, param_node: Node, source: bytes) -> str:
        if param_node.type == "identifier":
            return self._node_text(param_node, source)
        if param_node.type in ("default_parameter", "typed_parameter", "typed_default_parameter"):
            ids = [c for c in param_node.children if c.type == "identifier"]
            if ids:
                return self._node_text(ids[0], source)
        return self._node_text(param_node, source)

    # -- calls / routes -------------------------------------------------------

    def _handle_call(
        self,
        node: Node,
        source: bytes,
        parsed: ParsedFile,
        current_function: str | None,
        current_class: str | None,
    ) -> None:
        if not node.children:
            return
        callee = node.children[0]

        if callee.type == "identifier":
            parsed.calls.append(
                CallInfo(
                    callee_raw=self._node_text(callee, source),
                    is_member_call=False,
                    line=node.start_point[0] + 1,
                    caller_name=current_function,
                    caller_class=current_class,
                )
            )
        elif callee.type == "attribute":
            parsed.calls.append(
                CallInfo(
                    callee_raw=self._node_text(callee, source),
                    is_member_call=True,
                    line=node.start_point[0] + 1,
                    caller_name=current_function,
                    caller_class=current_class,
                )
            )

    def _handle_decorated_definition(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        func_def = self._first_child_of_type(node, "function_definition")
        if func_def is None:
            return
        handler_name = self._child_text(func_def, {"identifier"}, source)
        if not handler_name:
            return

        for child in node.children:
            if child.type != "decorator":
                continue
            route = self._extract_route_from_decorator(child, source, handler_name, parsed.path)
            if route:
                parsed.routes.append(route)

    def _extract_route_from_decorator(
        self, decorator_node: Node, source: bytes, handler_name: str, file_path: str
    ) -> RouteInfo | None:
        call_node = self._first_child_of_type(decorator_node, "call")
        if call_node is None:
            return None
        attribute = self._first_child_of_type(call_node, "attribute")
        if attribute is None or len(attribute.children) < 3:
            return None

        obj_node, prop_node = attribute.children[0], attribute.children[2]
        if obj_node.type != "identifier" or prop_node.type != "identifier":
            return None

        obj_text = self._node_text(obj_node, source)
        method_text = self._node_text(prop_node, source).lower()
        if obj_text not in ROUTE_DECORATOR_OBJECTS or method_text not in HTTP_METHODS:
            return None

        argument_list = self._first_child_of_type(call_node, "argument_list")
        if argument_list is None:
            return None
        arg_nodes = [c for c in argument_list.children if c.type not in ("(", ")", ",")]
        if not arg_nodes or arg_nodes[0].type != "string":
            return None

        return RouteInfo(
            method=method_text.upper(),
            path=self._string_literal_text(arg_nodes[0], source),
            handler=handler_name,
            file=file_path,
            line=decorator_node.start_point[0] + 1,
        )

    # -- node helpers -----------------------------------------------------

    @staticmethod
    def _node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _first_child_of_type(node: Node, type_name: str) -> Node | None:
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def _child_text(self, node: Node, types: set[str], source: bytes) -> str | None:
        for child in node.children:
            if child.type in types:
                return self._node_text(child, source)
        return None

    def _string_literal_text(self, string_node: Node, source: bytes) -> str:
        for child in string_node.children:
            if child.type == "string_content":
                return self._node_text(child, source)
        return ""


# =====================================================================
# 3. AST parsing -- JavaScript
# =====================================================================

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
ROUTER_OBJECT_NAMES = {"router", "app"}
PARAMETER_WRAPPER_TYPES = {"default_parameter", "required_parameter", "optional_parameter", "rest_parameter"}


class JavaScriptParser(BaseParser):
    """Tree-sitter-based extraction for JavaScript (and JSX).

    Walks the AST once, threading the enclosing function/class name down
    through recursion so calls and methods can be attributed to their
    containing scope. TypeScriptParser subclasses this and only swaps the
    grammar — the extraction logic (which node types mean what) is shared,
    since TS's syntax is a superset of JS's for everything we look at here.
    """

    language_name = "JavaScript"

    def __init__(self, ts_language: Language | None = None):
        self._parser = Parser(ts_language or Language(tsjs.language()))

    def parse(self, file_path: Path, relative_path: str) -> ParsedFile:
        try:
            source = file_path.read_bytes()
        except OSError as exc:
            raise ParseError(str(exc)) from exc

        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            raise ParseError(str(exc)) from exc

        parsed = ParsedFile(path=relative_path, language=self.language_name)
        self._visit(tree.root_node, source, parsed, current_function=None, current_class=None)
        return parsed

    # -- traversal ---------------------------------------------------------

    def _visit(
        self,
        node: Node,
        source: bytes,
        parsed: ParsedFile,
        current_function: str | None,
        current_class: str | None,
    ) -> None:
        node_type = node.type
        child_function = current_function
        child_class = current_class

        if node_type == "import_statement":
            self._handle_import(node, source, parsed)
        elif node_type == "export_statement":
            self._handle_export(node, source, parsed)
        elif node_type == "expression_statement":
            self._handle_expression_statement(node, source, parsed)
        elif node_type == "call_expression":
            self._handle_call(node, source, parsed, current_function, current_class)
            self._handle_route(node, source, parsed)
        elif node_type == "class_declaration":
            child_class = self._handle_class(node, source, parsed)
            child_function = None
        elif node_type == "function_declaration":
            name = self._child_text(node, {"identifier"}, source)
            if name:
                parsed.functions.append(
                    FunctionInfo(
                        name=name,
                        file=parsed.path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parameters=self._extract_parameters(node, source),
                        is_method=False,
                        class_name=None,
                    )
                )
                child_function = name
        elif node_type == "method_definition":
            name = self._child_text(node, {"property_identifier"}, source)
            if name:
                parsed.functions.append(
                    FunctionInfo(
                        name=name,
                        file=parsed.path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parameters=self._extract_parameters(node, source),
                        is_method=True,
                        class_name=current_class,
                    )
                )
                child_function = name
        elif node_type == "variable_declarator":
            handled_name = self._handle_variable_declarator(node, source, parsed)
            if handled_name:
                child_function = handled_name

        for child in node.children:
            self._visit(child, source, parsed, child_function, child_class)

    # -- imports / exports ---------------------------------------------------

    def _handle_import(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        string_node = self._first_child_of_type(node, "string")
        import_clause = self._first_child_of_type(node, "import_clause")
        if string_node is None:
            return

        imported_names: list[str] = []
        is_default = False

        if import_clause is not None:
            for child in import_clause.children:
                if child.type == "identifier":
                    imported_names.append(self._node_text(child, source))
                    is_default = True
                elif child.type == "namespace_import":
                    ids = [c for c in child.children if c.type == "identifier"]
                    if ids:
                        imported_names.append(self._node_text(ids[-1], source))
                elif child.type == "named_imports":
                    for spec in child.children:
                        if spec.type != "import_specifier":
                            continue
                        ids = [c for c in spec.children if c.type == "identifier"]
                        if ids:
                            imported_names.append(self._node_text(ids[-1], source))

        parsed.imports.append(
            ImportInfo(
                file=parsed.path,
                source=self._string_literal_text(string_node, source),
                imported_names=imported_names,
                is_default=is_default,
                line=node.start_point[0] + 1,
            )
        )

    def _handle_export(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        has_default = any(child.type == "default" for child in node.children)

        for child in node.children:
            if child.type == "function_declaration":
                name = self._child_text(child, {"identifier"}, source)
                if name:
                    parsed.exports.append(
                        ExportInfo(
                            file=parsed.path,
                            name=name,
                            kind="default" if has_default else "function",
                            line=node.start_point[0] + 1,
                        )
                    )
                return
            if child.type == "class_declaration":
                name = self._child_text(child, {"identifier", "type_identifier"}, source)
                if name:
                    parsed.exports.append(
                        ExportInfo(
                            file=parsed.path,
                            name=name,
                            kind="default" if has_default else "class",
                            line=node.start_point[0] + 1,
                        )
                    )
                return
            if child.type == "lexical_declaration":
                for declarator in child.children:
                    if declarator.type != "variable_declarator":
                        continue
                    name = self._child_text(declarator, {"identifier"}, source)
                    if name:
                        parsed.exports.append(
                            ExportInfo(file=parsed.path, name=name, kind="variable", line=node.start_point[0] + 1)
                        )
                return
            if child.type == "export_clause":
                for spec in child.children:
                    if spec.type != "export_specifier":
                        continue
                    ids = [c for c in spec.children if c.type == "identifier"]
                    if ids:
                        parsed.exports.append(
                            ExportInfo(
                                file=parsed.path,
                                name=self._node_text(ids[0], source),
                                kind="variable",
                                line=node.start_point[0] + 1,
                            )
                        )
                return
            if child.type == "identifier" and has_default:
                parsed.exports.append(
                    ExportInfo(
                        file=parsed.path,
                        name=self._node_text(child, source),
                        kind="default",
                        line=node.start_point[0] + 1,
                    )
                )
                return

    def _handle_expression_statement(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        """Covers CommonJS `module.exports = X` / `exports.y = z` and bare `require("x")`."""
        if not node.children:
            return
        inner = node.children[0]

        if inner.type == "assignment_expression":
            self._handle_commonjs_export(inner, node, source, parsed)
        elif inner.type == "call_expression" and inner.children:
            callee = inner.children[0]
            if callee.type == "identifier" and self._node_text(callee, source) == "require":
                arguments = inner.children[1] if len(inner.children) > 1 else None
                source_string = self._first_string_literal_text(arguments, source) if arguments else None
                if source_string:
                    parsed.imports.append(
                        ImportInfo(
                            file=parsed.path,
                            source=source_string,
                            imported_names=[],
                            is_default=False,
                            line=node.start_point[0] + 1,
                        )
                    )

    def _handle_commonjs_export(self, assign: Node, statement: Node, source: bytes, parsed: ParsedFile) -> None:
        if len(assign.children) < 2:
            return
        left, right = assign.children[0], assign.children[-1]
        if left.type != "member_expression":
            return

        left_text = self._node_text(left, source)
        if left_text == "module.exports":
            name = self._node_text(right, source) if right.type == "identifier" else "default"
            parsed.exports.append(
                ExportInfo(file=parsed.path, name=name, kind="default", line=statement.start_point[0] + 1)
            )
        elif left_text.startswith("module.exports.") or left_text.startswith("exports."):
            name = left_text.rsplit(".", 1)[-1]
            parsed.exports.append(
                ExportInfo(file=parsed.path, name=name, kind="variable", line=statement.start_point[0] + 1)
            )

    def _handle_variable_declarator(self, node: Node, source: bytes, parsed: ParsedFile) -> str | None:
        """Covers `const x = require("y")` and `const handler = () => {}`."""
        if len(node.children) < 2:
            return None
        name_node, value_node = node.children[0], node.children[-1]
        if name_node.type != "identifier":
            return None
        name = self._node_text(name_node, source)

        if value_node.type == "call_expression" and value_node.children:
            callee = value_node.children[0]
            if callee.type == "identifier" and self._node_text(callee, source) == "require":
                arguments = value_node.children[1] if len(value_node.children) > 1 else None
                source_string = self._first_string_literal_text(arguments, source) if arguments else None
                if source_string:
                    parsed.imports.append(
                        ImportInfo(
                            file=parsed.path,
                            source=source_string,
                            imported_names=[name],
                            is_default=True,
                            line=node.start_point[0] + 1,
                        )
                    )
            return None

        if value_node.type in ("arrow_function", "function_expression"):
            parsed.functions.append(
                FunctionInfo(
                    name=name,
                    file=parsed.path,
                    start_line=node.start_point[0] + 1,
                    end_line=value_node.end_point[0] + 1,
                    parameters=self._extract_parameters(value_node, source),
                    is_method=False,
                    class_name=None,
                )
            )
            return name

        return None

    # -- functions / classes -------------------------------------------------

    def _handle_class(self, node: Node, source: bytes, parsed: ParsedFile) -> str | None:
        name = self._child_text(node, {"identifier", "type_identifier"}, source)
        if not name:
            return None

        methods: list[str] = []
        body = self._first_child_of_type(node, "class_body")
        if body is not None:
            for child in body.children:
                if child.type == "method_definition":
                    method_name = self._child_text(child, {"property_identifier"}, source)
                    if method_name:
                        methods.append(method_name)

        parsed.classes.append(
            ClassInfo(
                name=name,
                file=parsed.path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                methods=methods,
            )
        )
        return name

    def _extract_parameters(self, func_node: Node, source: bytes) -> list[str]:
        params_node = self._first_child_of_type(func_node, "formal_parameters")
        if params_node is None:
            return []
        return [
            self._parameter_name(child, source)
            for child in params_node.children
            if child.type not in ("(", ")", ",")
        ]

    def _parameter_name(self, param_node: Node, source: bytes) -> str:
        if param_node.type == "identifier":
            return self._node_text(param_node, source)
        if param_node.type in PARAMETER_WRAPPER_TYPES:
            ids = [c for c in param_node.children if c.type == "identifier"]
            if ids:
                return self._node_text(ids[0], source)
        return self._node_text(param_node, source)

    # -- calls / routes -------------------------------------------------------

    def _handle_call(
        self,
        node: Node,
        source: bytes,
        parsed: ParsedFile,
        current_function: str | None,
        current_class: str | None,
    ) -> None:
        if not node.children:
            return
        callee = node.children[0]

        if callee.type == "identifier":
            callee_text = self._node_text(callee, source)
            if callee_text == "require":
                return  # handled at the statement/declarator level
            parsed.calls.append(
                CallInfo(
                    callee_raw=callee_text,
                    is_member_call=False,
                    line=node.start_point[0] + 1,
                    caller_name=current_function,
                    caller_class=current_class,
                )
            )
        elif callee.type == "member_expression":
            parsed.calls.append(
                CallInfo(
                    callee_raw=self._node_text(callee, source),
                    is_member_call=True,
                    line=node.start_point[0] + 1,
                    caller_name=current_function,
                    caller_class=current_class,
                )
            )

    def _handle_route(self, node: Node, source: bytes, parsed: ParsedFile) -> None:
        if not node.children:
            return
        callee = node.children[0]
        if callee.type != "member_expression" or len(callee.children) < 3:
            return

        obj_node, prop_node = callee.children[0], callee.children[2]
        if obj_node.type != "identifier" or prop_node.type != "property_identifier":
            return

        obj_text = self._node_text(obj_node, source)
        method_text = self._node_text(prop_node, source).lower()
        if obj_text not in ROUTER_OBJECT_NAMES or method_text not in HTTP_METHODS:
            return

        arguments = node.children[1] if len(node.children) > 1 else None
        if arguments is None:
            return
        arg_nodes = [c for c in arguments.children if c.type not in ("(", ")", ",")]
        if not arg_nodes or arg_nodes[0].type != "string":
            return

        handler_text = "<inline>"
        if len(arg_nodes) > 1 and arg_nodes[-1].type in ("identifier", "member_expression"):
            handler_text = self._node_text(arg_nodes[-1], source)

        parsed.routes.append(
            RouteInfo(
                method=method_text.upper(),
                path=self._string_literal_text(arg_nodes[0], source),
                handler=handler_text,
                file=parsed.path,
                line=node.start_point[0] + 1,
            )
        )

    # -- node helpers -----------------------------------------------------

    @staticmethod
    def _node_text(node: Node, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _first_child_of_type(node: Node, type_name: str) -> Node | None:
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def _child_text(self, node: Node, types: set[str], source: bytes) -> str | None:
        for child in node.children:
            if child.type in types:
                return self._node_text(child, source)
        return None

    def _string_literal_text(self, string_node: Node, source: bytes) -> str:
        for child in string_node.children:
            if child.type == "string_fragment":
                return self._node_text(child, source)
        return ""

    def _first_string_literal_text(self, arguments_node: Node, source: bytes) -> str | None:
        for child in arguments_node.children:
            if child.type == "string":
                return self._string_literal_text(child, source)
        return None


# =====================================================================
# 4. AST parsing -- TypeScript
# =====================================================================

class TypeScriptParser(JavaScriptParser):
    """TypeScript/TSX extraction.

    TS syntax is a superset of JS for every node type JavaScriptParser
    looks at (imports, exports, functions, classes, calls, member access) —
    the extra type annotations just show up as sibling nodes we don't visit,
    and class/interface names use `type_identifier` instead of `identifier`,
    which JavaScriptParser already accepts in its name lookups. So the only
    thing that actually differs here is which grammar to load.
    """

    language_name = "TypeScript"

    def __init__(self, tsx: bool = False):
        grammar = tsts.language_tsx() if tsx else tsts.language_typescript()
        super().__init__(ts_language=Language(grammar))


# =====================================================================
# 5. Parser factory / language dispatch
# =====================================================================

class ParserFactory:
    """Extension -> parser lookup.

    Grammars are relatively expensive to build, so each parser is a
    singleton reused across every file of that language, not rebuilt per
    file. Adding a new language later is a one-line addition to
    `_PARSERS_BY_EXTENSION` plus a new parser class — nothing else in
    CodeMap needs to change, since everything downstream only depends on
    BaseParser/ParsedFile.
    """

    def __init__(self):
        javascript = JavaScriptParser()
        typescript = TypeScriptParser(tsx=False)
        tsx = TypeScriptParser(tsx=True)
        python = PythonParser()

        self._parsers_by_extension: dict[str, BaseParser] = {
            ".js": javascript,
            ".jsx": javascript,
            ".mjs": javascript,
            ".cjs": javascript,
            ".ts": typescript,
            ".tsx": tsx,
            ".py": python,
        }

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._parsers_by_extension.keys())

    def get_parser(self, extension: str) -> BaseParser | None:
        return self._parsers_by_extension.get(extension)


parser_factory = ParserFactory()


# =====================================================================
# 6. Import/export resolution -- raw import strings to local files
# =====================================================================

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


# =====================================================================
# 7. Code intelligence construction (symbols, imports, exports,
#    routes, and relationships -- Tree-sitter parsing orchestration)
# =====================================================================

@dataclass
class ParseStatsRecord:
    files_parsed: int = 0
    files_skipped: int = 0
    parse_errors: int = 0


@dataclass
class SymbolRecord:
    kind: str  # "function" | "class"
    name: str
    file: str
    start_line: int
    end_line: int
    parameters: list[str] = field(default_factory=list)
    is_method: bool = False
    class_name: str | None = None
    methods: list[str] = field(default_factory=list)


@dataclass
class ImportRecord:
    file: str
    source: str
    imported_names: list[str]
    is_default: bool
    resolved_target: str | None
    is_external: bool
    line: int


@dataclass
class ExportRecord:
    file: str
    name: str
    kind: str
    line: int


@dataclass
class RelationshipRecord:
    source: str
    target: str | None
    type: str  # "imports" | "contains" | "calls"
    resolved: bool = True
    raw_callee: str | None = None


@dataclass
class RouteRecord:
    method: str
    path: str
    handler: str
    file: str
    line: int


@dataclass
class ParsedFileRecord:
    path: str
    language: str
    functions_count: int = 0
    classes_count: int = 0
    imports_count: int = 0
    exports_count: int = 0
    parse_error: str | None = None


@dataclass
class RepositoryIntelligenceInfo:
    name: str
    languages: list[str]
    frameworks: list[str]


@dataclass
class CodeIntelligenceResult:
    repository: RepositoryIntelligenceInfo
    files: list[ParsedFileRecord]
    symbols: list[SymbolRecord]
    imports: list[ImportRecord]
    exports: list[ExportRecord]
    relationships: list[RelationshipRecord]
    routes: list[RouteRecord]
    stats: ParseStatsRecord

    def to_dict(self) -> dict:
        return asdict(self)


class CodeIntelligenceAnalyzer:
    """Runs Tree-sitter parsing across a repository and builds the code
    intelligence graph: symbols, imports/exports, relationships, and routes.

    Takes the Day 2 RepositoryAnalyzer's result as input rather than
    re-scanning the filesystem — repository/language/framework info and the
    full file list are already computed there, so this layer only adds what
    Tree-sitter uniquely provides.
    """

    def __init__(self, repository_path: Path, day2_result: AnalysisResult, max_file_size_bytes: int):
        self.repository_path = repository_path
        self.day2_result = day2_result
        self.max_file_size_bytes = max_file_size_bytes

    def analyze(self) -> CodeIntelligenceResult:
        stats = ParseStatsRecord()
        parsed_files: dict[str, ParsedFile] = {}
        file_entries: list[ParsedFileRecord] = []
        all_paths = [entry["path"] for entry in self.day2_result.files]

        for entry in self.day2_result.files:
            path, extension, language = entry["path"], entry["extension"], entry["language"]
            parser = parser_factory.get_parser(extension)
            if parser is None:
                continue

            if entry["size_bytes"] > self.max_file_size_bytes:
                stats.files_skipped += 1
                file_entries.append(ParsedFileRecord(path=path, language=language, parse_error="skipped: exceeds max file size"))
                continue

            try:
                parsed = parser.parse(self.repository_path / path, path)
            except ParseError as exc:
                stats.parse_errors += 1
                logger.warning("Failed to parse %s: %s", path, exc)
                file_entries.append(ParsedFileRecord(path=path, language=language, parse_error=str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - a single bad file must never abort the repo scan
                stats.parse_errors += 1
                logger.warning("Unexpected error parsing %s: %s", path, exc)
                file_entries.append(ParsedFileRecord(path=path, language=language, parse_error=str(exc)))
                continue

            stats.files_parsed += 1
            parsed_files[path] = parsed
            file_entries.append(
                ParsedFileRecord(
                    path=path,
                    language=language,
                    functions_count=len(parsed.functions),
                    classes_count=len(parsed.classes),
                    imports_count=len(parsed.imports),
                    exports_count=len(parsed.exports),
                )
            )

        resolver = LocalDependencyResolver(all_paths)
        function_index, method_index, class_index = self._build_symbol_indices(parsed_files)

        symbols: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        exports: list[ExportRecord] = []
        relationships: list[RelationshipRecord] = []
        routes: list[RouteRecord] = []
        local_import_targets: dict[str, dict[str, str]] = {}

        for path, parsed in parsed_files.items():
            for fn in parsed.functions:
                symbols.append(
                    SymbolRecord(
                        kind="function",
                        name=fn.name,
                        file=fn.file,
                        start_line=fn.start_line,
                        end_line=fn.end_line,
                        parameters=fn.parameters,
                        is_method=fn.is_method,
                        class_name=fn.class_name,
                    )
                )
                relationships.append(RelationshipRecord(source=path, target=symbol_id(path, fn.name), type="contains"))

            for cls in parsed.classes:
                symbols.append(
                    SymbolRecord(
                        kind="class",
                        name=cls.name,
                        file=cls.file,
                        start_line=cls.start_line,
                        end_line=cls.end_line,
                        methods=cls.methods,
                    )
                )
                relationships.append(RelationshipRecord(source=path, target=symbol_id(path, cls.name), type="contains"))

            for imp in parsed.imports:
                entry, import_rels = self._resolve_import(path, imp, parsed.language, resolver)
                imports.append(entry)
                relationships.extend(import_rels)
                if entry.resolved_target and imp.imported_names:
                    bucket = local_import_targets.setdefault(path, {})
                    for name in imp.imported_names:
                        bucket[name] = entry.resolved_target

            for exp in parsed.exports:
                exports.append(ExportRecord(file=exp.file, name=exp.name, kind=exp.kind, line=exp.line))

            for route in parsed.routes:
                routes.append(RouteRecord(method=route.method, path=route.path, handler=route.handler, file=route.file, line=route.line))

        for path, parsed in parsed_files.items():
            for call in parsed.calls:
                relationship = self._resolve_call(
                    path, call, parsed.language, function_index, method_index, class_index, local_import_targets
                )
                if relationship is not None:
                    relationships.append(relationship)

        repository_info = RepositoryIntelligenceInfo(
            name=self.day2_result.repository_name,
            languages=list(self.day2_result.languages.keys()),
            frameworks=self.day2_result.frameworks,
        )

        return CodeIntelligenceResult(
            repository=repository_info,
            files=file_entries,
            symbols=symbols,
            imports=imports,
            exports=exports,
            relationships=relationships,
            routes=routes,
            stats=stats,
        )

    # -- import resolution -------------------------------------------------

    def _resolve_import(
        self, path: str, imp, language: str, resolver: LocalDependencyResolver
    ) -> tuple[ImportRecord, list[RelationshipRecord]]:
        relationships: list[RelationshipRecord] = []

        if language == "Python" and imp.source.lstrip(".") == "" and imp.imported_names:
            # `from . import a, b` -- each name is its own sibling module,
            # so there's no single resolved_target for the statement itself.
            resolved_target = None
            for name in imp.imported_names:
                resolved = resolver.resolve_python_relative_name(path, imp.source, name)
                if resolved.target:
                    resolved_target = resolved_target or resolved.target
                    relationships.append(RelationshipRecord(source=path, target=resolved.target, type="imports"))
            entry = ImportRecord(
                file=path,
                source=imp.source,
                imported_names=imp.imported_names,
                is_default=imp.is_default,
                resolved_target=resolved_target,
                is_external=False,
                line=imp.line,
            )
            return entry, relationships

        resolved = resolver.resolve_python(path, imp.source) if language == "Python" else resolver.resolve_javascript(path, imp.source)

        entry = ImportRecord(
            file=path,
            source=imp.source,
            imported_names=imp.imported_names,
            is_default=imp.is_default,
            resolved_target=resolved.target,
            is_external=resolved.is_external,
            line=imp.line,
        )
        if resolved.target:
            relationships.append(RelationshipRecord(source=path, target=resolved.target, type="imports"))
        return entry, relationships

    # -- call resolution -------------------------------------------------

    def _build_symbol_indices(
        self, parsed_files: dict[str, ParsedFile]
    ) -> tuple[dict[tuple[str, str], FunctionInfo], dict[tuple[str, str, str], FunctionInfo], set[tuple[str, str]]]:
        function_index: dict[tuple[str, str], FunctionInfo] = {}
        method_index: dict[tuple[str, str, str], FunctionInfo] = {}
        class_index: set[tuple[str, str]] = set()

        for path, parsed in parsed_files.items():
            for fn in parsed.functions:
                if fn.is_method and fn.class_name:
                    method_index[(path, fn.class_name, fn.name)] = fn
                else:
                    function_index[(path, fn.name)] = fn
            for cls in parsed.classes:
                class_index.add((path, cls.name))

        return function_index, method_index, class_index

    def _resolve_call(
        self,
        path: str,
        call: CallInfo,
        language: str,
        function_index: dict[tuple[str, str], FunctionInfo],
        method_index: dict[tuple[str, str, str], FunctionInfo],
        class_index: set[tuple[str, str]],
        local_import_targets: dict[str, dict[str, str]],
    ) -> RelationshipRecord | None:
        if not call.caller_name:
            return None  # nothing to attach an unattributed top-level call to
        caller_symbol = symbol_id(path, call.caller_name)

        if not call.is_member_call:
            callee_name = call.callee_raw

            if (path, callee_name) in function_index or (path, callee_name) in class_index:
                return RelationshipRecord(source=caller_symbol, target=symbol_id(path, callee_name), type="calls")

            target_file = local_import_targets.get(path, {}).get(callee_name)
            if target_file and ((target_file, callee_name) in function_index or (target_file, callee_name) in class_index):
                return RelationshipRecord(source=caller_symbol, target=symbol_id(target_file, callee_name), type="calls")

        elif language == "Python" and call.callee_raw.startswith("self.") and call.caller_class:
            method_name = call.callee_raw.split(".", 1)[1]
            if (path, call.caller_class, method_name) in method_index:
                return RelationshipRecord(source=caller_symbol, target=symbol_id(path, method_name), type="calls")

        return RelationshipRecord(source=caller_symbol, target=None, type="calls", resolved=False, raw_callee=call.callee_raw)


# =====================================================================
# 8. Analysis caching -- on-disk persistence + on-demand build service
# =====================================================================

REPOSITORY_FILE = "repository.json"
CODE_STRUCTURE_FILE = "code_structure.json"
RELATIONSHIPS_FILE = "relationships.json"


class AnalysisStorage:
    """Persists a CodeIntelligenceResult as JSON, split into three files
    rather than one deeply nested blob, per the Day 3 brief. This is a
    deliberately temporary storage layer — no database yet — but the split
    (repository/file-level facts, code structure, relationship graph) maps
    directly onto what would become separate tables if this moves to
    Postgres later, so today's shape isn't a dead end.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or settings.analysis_output_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, repository_id: str, result: CodeIntelligenceResult) -> Path:
        data = result.to_dict()
        repo_dir = self.base_dir / repository_id
        repo_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(
            repo_dir / REPOSITORY_FILE,
            {"repository": data["repository"], "files": data["files"], "stats": data["stats"]},
        )
        self._write_json(
            repo_dir / CODE_STRUCTURE_FILE,
            {
                "symbols": data["symbols"],
                "imports": data["imports"],
                "exports": data["exports"],
                "routes": data["routes"],
            },
        )
        self._write_json(repo_dir / RELATIONSHIPS_FILE, {"relationships": data["relationships"]})
        return repo_dir

    def load(self, repository_id: str) -> dict | None:
        repo_dir = self.base_dir / repository_id
        paths = [repo_dir / name for name in (REPOSITORY_FILE, CODE_STRUCTURE_FILE, RELATIONSHIPS_FILE)]
        if not all(path.exists() for path in paths):
            return None

        repository_data, code_structure_data, relationships_data = (self._read_json(path) for path in paths)

        return {
            **repository_data,
            **code_structure_data,
            **relationships_data,
        }

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


analysis_storage = AnalysisStorage()



def run_and_store_code_intelligence(
    repository_path: Path, day2_result: AnalysisResult | None = None
) -> CodeIntelligenceResult:
    """Runs the Day 2 + Day 3 analysis pipeline and persists the result.

    `day2_result` can be passed in when the caller already computed it
    (e.g. the context builder, which also needs it for repository metadata)
    to avoid scanning the repository twice. When it's not, this reads the
    cached canonical snapshot (see repository.get_repository_snapshot)
    rather than re-walking the filesystem directly -- there's still only
    ever one Day 2 scan per repository version, no matter which caller
    triggers it first.
    """
    if day2_result is None:
        day2_result = get_repository_snapshot(repository_path)

    intelligence = CodeIntelligenceAnalyzer(
        repository_path, day2_result, settings.max_parseable_file_size_bytes
    ).analyze()
    analysis_storage.save(repository_path.name, intelligence)
    return intelligence


def get_or_build_code_intelligence(repository_path: Path, day2_result: AnalysisResult | None = None) -> dict:
    """Returns the stored code intelligence analysis, building it on demand
    if `POST /repository/analyze-code` hasn't been run yet — the AI layer
    shouldn't require the user to have visited the debug view first."""
    data = analysis_storage.load(repository_path.name)
    if data is not None:
        return data
    return run_and_store_code_intelligence(repository_path, day2_result).to_dict()


# =====================================================================
# 9. Relationship analysis -- shared file-level edge index
#    (used by graph/impact/health below)
# =====================================================================

def symbol_file(sid: str) -> str:
    return sid.split("::", 1)[0]


def external_package_name(source: str, language: str) -> str:
    if source.startswith("@"):
        parts = source.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else source
    if language == "Python":
        return source.split(".")[0]
    return source.split("/")[0]


@dataclass(frozen=True)
class FileEdge:
    source: str
    target: str
    type: str  # "imports" | "calls"


class RelationshipIndex:
    """Indexes Day 3 code intelligence into fast file-level lookups for
    graph/impact traversal."""

    def __init__(self, intelligence: dict):
        self.intelligence = intelligence
        self.files_by_path = {f["path"]: f for f in intelligence["files"]}
        self.file_paths = set(self.files_by_path.keys())

        self.file_edges: dict[tuple[str, str, str], int] = {}
        self.external_by_file: dict[tuple[str, str], dict] = {}
        self._forward: dict[str, list[FileEdge]] = defaultdict(list)
        self._reverse: dict[str, list[FileEdge]] = defaultdict(list)

        self._collect(intelligence)

    def _collect(self, intelligence: dict) -> None:
        for rel in intelligence["relationships"]:
            if rel["type"] == "imports":
                source, target = rel["source"], rel["target"]
                if target and source in self.file_paths and target in self.file_paths and source != target:
                    self._add_file_edge(source, target, "imports")
            elif rel["type"] == "calls":
                if not rel.get("resolved") or not rel.get("target"):
                    continue
                source_file = symbol_file(rel["source"])
                target_file = symbol_file(rel["target"])
                if source_file != target_file and source_file in self.file_paths and target_file in self.file_paths:
                    self._add_file_edge(source_file, target_file, "calls")

        for imp in intelligence["imports"]:
            if not imp["is_external"]:
                continue
            file = imp["file"]
            if file not in self.file_paths:
                continue
            language = self.files_by_path[file]["language"]
            package = external_package_name(imp["source"], language)
            key = (file, f"external:{package}")
            entry = self.external_by_file.setdefault(key, {"weight": 0, "label": package})
            entry["weight"] += 1

        for (source, target, edge_type) in self.file_edges:
            edge = FileEdge(source, target, edge_type)
            self._forward[source].append(edge)
            self._reverse[target].append(edge)

    def _add_file_edge(self, source: str, target: str, edge_type: str) -> None:
        key = (source, target, edge_type)
        self.file_edges[key] = self.file_edges.get(key, 0) + 1

    def forward(self, path: str) -> list[FileEdge]:
        return self._forward.get(path, [])

    def reverse(self, path: str) -> list[FileEdge]:
        """Files that depend on `path` (import it or call into it)."""
        return self._reverse.get(path, [])


# =====================================================================
# 10. Architecture/dependency graph construction
# =====================================================================

FRONTEND_MARKERS = {"frontend", "client", "web"}
BACKEND_MARKERS = {"backend", "server", "api"}
ROOT_FOLDER_ID = "."
MAX_EXTERNAL_NODES = 30

FileEdgeKey = tuple[str, str, str]  # (source_path, target_path, edge_type)
ExternalEdgeKey = tuple[str, str]  # (file_path, external_node_id)


def _top_level_folder(path: str) -> str:
    return _folder_at_depth(path, 1)


def _folder_at_depth(path: str, depth: int) -> str:
    """Groups `path` by its first `depth` folder segments. A file that
    doesn't have `depth` segments of its own (e.g. a file sitting directly
    in the folder being grouped at this depth) is grouped under its
    immediate parent instead, same as `depth=1` already did for root-level
    files -- this just generalizes that to any depth."""
    parts = path.split("/")
    if len(parts) <= depth:
        return "/".join(parts[:-1]) or ROOT_FOLDER_ID
    return "/".join(parts[:depth])


class GraphBuilder:
    def __init__(self, day2_files: list[dict], intelligence: dict, max_file_nodes: int, index: RelationshipIndex | None = None):
        self.day2_files = day2_files
        self.intelligence = intelligence
        self.max_file_nodes = max_file_nodes
        self.index = index or RelationshipIndex(intelligence)

    def build(self, focus: str | None = None) -> GraphResponse:
        lines_by_path = {f["path"]: f["lines"] for f in self.day2_files}
        intel_files = self.index.files_by_path
        file_paths = list(intel_files.keys())
        total_files = len(file_paths)

        layer_by_path = self._guess_layers(file_paths)
        file_edges, external_by_file = self.index.file_edges, self.index.external_by_file

        if focus:
            focus = focus.strip("/")
            scoped = self._scope_to_focus(focus, file_paths, file_edges)

            if len(scoped) > self.max_file_nodes:
                # A single extra folder-depth level isn't always enough for a
                # monorepo (e.g. focusing "packages" can still contain hundreds
                # of files one level down) -- keep grouping one level deeper
                # until the node count is manageable, or we run out of
                # meaningful depth to add.
                depth = focus.count("/") + 2
                nodes, edges = self._build_folder_graph(scoped, file_edges, external_by_file, depth, root=focus)
                return GraphResponse(
                    nodes=nodes,
                    edges=edges,
                    mode="folders",
                    truncated=True,
                    analyzed_file_count=total_files,
                    message=(
                        f"'{focus}' contains {len(scoped)} files. Showing its subfolders — "
                        "click one or use search to explore specific files."
                    ),
                )

            nodes = self._build_file_nodes(scoped, intel_files, lines_by_path, layer_by_path)
            nodes += self._build_external_nodes(external_by_file, scoped)
            edges = self._build_file_edges(file_edges, scoped)
            edges += self._build_external_edges(external_by_file, scoped)
            return GraphResponse(
                nodes=nodes,
                edges=edges,
                mode="files",
                truncated=len(scoped) < total_files,
                analyzed_file_count=total_files,
                message=f"Showing {len(scoped)} files under '{focus}' and their direct connections.",
            )

        if total_files > self.max_file_nodes:
            nodes, edges = self._build_folder_graph(file_paths, file_edges, external_by_file, depth=1, root=ROOT_FOLDER_ID)
            return GraphResponse(
                nodes=nodes,
                edges=edges,
                mode="folders",
                truncated=True,
                analyzed_file_count=total_files,
                message=(
                    f"{total_files} files have analyzable code relationships. Showing the top-level folder "
                    "structure first — click a folder or use search to explore specific files."
                ),
            )

        all_paths = set(file_paths)
        nodes = self._build_file_nodes(file_paths, intel_files, lines_by_path, layer_by_path)
        nodes += self._build_external_nodes(external_by_file, all_paths)
        edges = self._build_file_edges(file_edges, all_paths)
        edges += self._build_external_edges(external_by_file, all_paths)
        return GraphResponse(
            nodes=nodes, edges=edges, mode="files", truncated=False, analyzed_file_count=total_files, message=None
        )

    # -- layer heuristics -----------------------------------------------

    def _guess_layers(self, file_paths: list[str]) -> dict[str, str]:
        """Tags files as frontend/backend only when the repo's own top-level
        folder names make that unambiguous. Otherwise leaves layers unset
        rather than inventing an architecture that isn't there."""
        top_dirs = {_top_level_folder(p) for p in file_paths}
        if not (top_dirs & FRONTEND_MARKERS and top_dirs & BACKEND_MARKERS):
            return {}

        layers: dict[str, str] = {}
        for path in file_paths:
            top = _top_level_folder(path)
            if top in FRONTEND_MARKERS:
                layers[path] = "frontend"
            elif top in BACKEND_MARKERS:
                layers[path] = "backend"
        return layers

    # -- scoping / aggregation -------------------------------------------

    def _scope_to_focus(self, focus: str, file_paths: list[str], file_edges: dict[FileEdgeKey, int]) -> set[str]:
        focus = focus.strip("/")
        direct = {p for p in file_paths if p == focus or p.startswith(f"{focus}/")}
        neighbors: set[str] = set()
        for source, target, _ in file_edges:
            if source in direct:
                neighbors.add(target)
            if target in direct:
                neighbors.add(source)
        return direct | neighbors

    def _build_folder_graph(
        self,
        file_paths: list[str],
        file_edges: dict[FileEdgeKey, int],
        external_by_file: dict[ExternalEdgeKey, dict],
        depth: int,
        root: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        folder_of = {p: _folder_at_depth(p, depth) for p in file_paths}
        folder_counts: dict[str, int] = {}
        for folder in folder_of.values():
            folder_counts[folder] = folder_counts.get(folder, 0) + 1

        def _label(folder: str) -> str:
            if folder == root:
                return "(root)" if root == ROOT_FOLDER_ID else f"{root} (direct files)"
            return folder

        nodes = [
            GraphNode(
                id=folder,
                type="folder",
                data=GraphNodeData(label=_label(folder), path=folder, file_count=count),
            )
            for folder, count in sorted(folder_counts.items())
        ]

        folder_edges: dict[FileEdgeKey, int] = {}
        for (source, target, edge_type), weight in file_edges.items():
            # `file_paths` (and so `folder_of`) may be a scoped subset of the
            # repo rather than every file -- skip edges that reach outside it.
            if source not in folder_of or target not in folder_of:
                continue
            source_folder, target_folder = folder_of[source], folder_of[target]
            if source_folder == target_folder:
                continue
            key = (source_folder, target_folder, edge_type)
            folder_edges[key] = folder_edges.get(key, 0) + weight

        edges = [
            GraphEdge(id=f"{s}->{t}:{et}", source=s, target=t, type=et, weight=w)
            for (s, t, et), w in folder_edges.items()
        ]

        folder_external: dict[ExternalEdgeKey, dict] = {}
        total_weight_by_external: dict[str, int] = {}
        for (file, external_id), entry in external_by_file.items():
            if file not in folder_of:
                continue
            folder = folder_of[file]
            key = (folder, external_id)
            bucket = folder_external.setdefault(key, {"weight": 0, "label": entry["label"]})
            bucket["weight"] += entry["weight"]
            total_weight_by_external[external_id] = total_weight_by_external.get(external_id, 0) + entry["weight"]

        # An aggregated view is dominated by however many *folders* there
        # are, not files -- an uncapped external list (one node per package
        # ever imported, repo-wide) can dwarf that and bury the actual
        # repository structure. Keep only the packages most imported overall.
        kept_external_ids = {
            eid for eid, _ in sorted(total_weight_by_external.items(), key=lambda item: item[1], reverse=True)[:MAX_EXTERNAL_NODES]
        }

        seen_external: dict[str, str] = {}
        for (folder, external_id), entry in folder_external.items():
            if external_id not in kept_external_ids:
                continue
            edges.append(
                GraphEdge(id=f"{folder}->{external_id}", source=folder, target=external_id, type="imports", weight=entry["weight"])
            )
            seen_external.setdefault(external_id, entry["label"])

        nodes += [GraphNode(id=eid, type="external", data=GraphNodeData(label=label)) for eid, label in seen_external.items()]
        return nodes, edges

    # -- node/edge construction -------------------------------------------

    def _build_file_nodes(
        self,
        paths,
        intel_files: dict[str, dict],
        lines_by_path: dict[str, int],
        layer_by_path: dict[str, str],
    ) -> list[GraphNode]:
        nodes = []
        for path in paths:
            entry = intel_files[path]
            nodes.append(
                GraphNode(
                    id=path,
                    type="file",
                    data=GraphNodeData(
                        label=posixpath.basename(path),
                        path=path,
                        language=entry["language"],
                        lines=lines_by_path.get(path),
                        functions=entry.get("functions_count"),
                        classes=entry.get("classes_count"),
                        imports=entry.get("imports_count"),
                        exports=entry.get("exports_count"),
                        layer=layer_by_path.get(path),
                        parse_error=entry.get("parse_error"),
                    ),
                )
            )
        return nodes

    def _build_file_edges(self, file_edges: dict[FileEdgeKey, int], scoped_paths: set[str]) -> list[GraphEdge]:
        return [
            GraphEdge(id=f"{source}->{target}:{edge_type}", source=source, target=target, type=edge_type, weight=weight)
            for (source, target, edge_type), weight in file_edges.items()
            if source in scoped_paths and target in scoped_paths
        ]

    def _build_external_edges(
        self, external_by_file: dict[ExternalEdgeKey, dict], scoped_paths: set[str]
    ) -> list[GraphEdge]:
        return [
            GraphEdge(id=f"{file}->{external_id}", source=file, target=external_id, type="imports", weight=entry["weight"])
            for (file, external_id), entry in external_by_file.items()
            if file in scoped_paths
        ]

    def _build_external_nodes(
        self, external_by_file: dict[ExternalEdgeKey, dict], scoped_paths: set[str]
    ) -> list[GraphNode]:
        seen: dict[str, str] = {}
        for (file, external_id), entry in external_by_file.items():
            if file in scoped_paths and external_id not in seen:
                seen[external_id] = entry["label"]
        return [GraphNode(id=eid, type="external", data=GraphNodeData(label=label)) for eid, label in seen.items()]


def build_repository_graph(focus: str | None = None) -> GraphResponse:
    """Builds the repository graph from the existing Day 2/3 analysis --
    reuses the cached canonical snapshot and stored Day 3 code intelligence
    if it's already been computed, exactly like the AI endpoints do, so
    visiting the graph doesn't require a separate manual analysis step."""
    repository_path = git_clone_service.get_latest_cloned_repository()
    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    builder = GraphBuilder(day2_result.files, intelligence, settings.graph_max_file_nodes)
    return builder.build(focus=focus)


# =====================================================================
# 11. API/route detection + change-impact analysis
# =====================================================================


JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"}

# axios.get("/x"), axios.post('/x'), axios.request({ url: "/x", method: "post" })
_AXIOS_METHOD_PATTERN = re.compile(
    r"axios\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['\"`]([^'\"`]+)['\"`]", re.IGNORECASE
)

# fetch("/x") or fetch("/x", { method: "POST", ... })
_FETCH_PATTERN = re.compile(
    r"fetch\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*(?:,\s*\{([^}]*)\})?", re.IGNORECASE | re.DOTALL
)
_FETCH_METHOD_IN_OPTIONS = re.compile(r"method\s*:\s*['\"`](\w+)['\"`]", re.IGNORECASE)


@dataclass(frozen=True)
class DetectedApiCall:
    method: str
    path: str
    line: int


def extract_api_calls(content: str, extension: str) -> list[DetectedApiCall]:
    """Finds axios/fetch calls with a string-literal URL. Calls with a
    dynamic/templated URL (`` `/users/${id}` `` or a variable) are skipped
    rather than guessed at."""
    if extension not in JS_EXTENSIONS:
        return []

    calls: list[DetectedApiCall] = []
    for match in _AXIOS_METHOD_PATTERN.finditer(content):
        method, path = match.group(1).upper(), match.group(2)
        if "${" in path:
            continue
        line = content.count("\n", 0, match.start()) + 1
        calls.append(DetectedApiCall(method=method, path=path, line=line))

    for match in _FETCH_PATTERN.finditer(content):
        path, options = match.group(1), match.group(2) or ""
        if "${" in path:
            continue
        method_match = _FETCH_METHOD_IN_OPTIONS.search(options)
        method = method_match.group(1).upper() if method_match else "GET"
        line = content.count("\n", 0, match.start()) + 1
        calls.append(DetectedApiCall(method=method, path=path, line=line))

    return calls


def normalize_route_path(path: str) -> str:
    """Strips a leading API mount prefix so `/api/login` and `/login` can be
    compared. Deliberately narrow (`/api`, `/api/v1`) -- not a general
    router-mount resolver, since Day 3 doesn't track `app.use()` prefixes."""
    stripped = path
    for prefix in ("/api/v1", "/api/v2", "/api"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):] or "/"
            break
    return stripped.rstrip("/") or "/"


def match_route(method: str, path: str, routes: list[dict]) -> tuple[dict | None, str]:
    """Matches a detected frontend API call to a Day 3 RouteEntry.

    Returns (route, confidence). Never guesses past what the path/method
    text actually supports -- an unmatched call comes back as (None, "unknown")
    rather than a fabricated best-effort target.
    """
    candidates = [r for r in routes if r["method"].upper() == method.upper()]

    for route in candidates:
        if route["path"] == path:
            return route, "high"

    normalized_call = normalize_route_path(path)
    for route in candidates:
        if normalize_route_path(route["path"]) == normalized_call:
            return route, "medium"

    return None, "unknown"


MAX_DEPTH = 6
MAX_DEPENDENTS = 200
MAX_RELATED_FILE_SCAN = 300
ENTRY_POINT_BASENAMES = {"main", "index", "app", "server", "__init__"}


class ImpactAnalyzerError(Exception):
    pass


class ImpactAnalyzer:
    def __init__(self, repository_path: Path, intelligence: dict, index: RelationshipIndex):
        self.repository_path = repository_path
        self.intelligence = intelligence
        self.index = index
        self.routes = intelligence["routes"]

    def analyze(self, file: str) -> ImpactResponse:
        if file not in self.index.file_paths:
            raise ImpactAnalyzerError(f"'{file}' was not found in this repository's analyzed source files.")

        visited: dict[str, ImpactedFile] = {}
        seen = {file}
        queue = deque([(file, 0)])
        truncated = False

        while queue:
            current, depth = queue.popleft()
            if depth >= MAX_DEPTH:
                continue
            for edge in self.index.reverse(current):
                if edge.source in seen:
                    existing = visited.get(edge.source)
                    if existing and edge.type not in existing.via:
                        existing.via.append(edge.type)
                    continue
                if len(seen) >= MAX_DEPENDENTS:
                    truncated = True
                    continue
                seen.add(edge.source)
                entry = ImpactedFile(path=edge.source, depth=depth + 1, via=[edge.type], discovered_via=current)
                visited[edge.source] = entry
                queue.append((edge.source, depth + 1))

        direct = sorted((f for f in visited.values() if f.depth == 1), key=lambda f: f.path)
        indirect = sorted((f for f in visited.values() if f.depth > 1), key=lambda f: f.path)
        impacted_paths = seen  # includes `file` itself

        related_routes = [
            RelatedRoute(method=r["method"], path=r["path"], file=r["file"])
            for r in self.routes
            if r["file"] in impacted_paths
        ]
        related_files = self._find_related_frontend_callers(related_routes, exclude=impacted_paths)

        risk = self._score_risk(file, direct, indirect, related_routes)

        return ImpactResponse(
            file=file,
            risk=risk,
            direct_dependents=direct,
            indirect_dependents=indirect,
            related_routes=related_routes,
            related_files=related_files,
            truncated=truncated,
        )

    def _find_related_frontend_callers(self, related_routes: list[RelatedRoute], exclude: set[str]) -> list[RelatedFile]:
        """Files that call one of the impacted routes over HTTP -- a route-level
        connection, not a static import/call edge, so it's reported separately
        from direct/indirect dependents rather than folded into them."""
        if not related_routes:
            return []

        route_dicts = [route.model_dump() for route in related_routes]
        related: list[RelatedFile] = []
        candidates = [p for p in self.index.file_paths if p not in exclude][:MAX_RELATED_FILE_SCAN]

        for path in candidates:
            extension = posixpath.splitext(path)[1]
            try:
                content = (self.repository_path / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for call in extract_api_calls(content, extension):
                route, confidence = match_route(call.method, call.path, route_dicts)
                if route:
                    related.append(RelatedFile(path=path, route=f"{route['method']} {route['path']}", confidence=confidence))
                    break

        return related

    def _score_risk(
        self, file: str, direct: list[ImpactedFile], indirect: list[ImpactedFile], related_routes: list[RelatedRoute]
    ) -> RiskEstimate:
        symbol_count = sum(1 for s in self.intelligence["symbols"] if s["file"] == file)
        is_entry_point = posixpath.splitext(posixpath.basename(file))[0].lower() in ENTRY_POINT_BASENAMES

        score = (
            len(direct) * 8
            + len(indirect) * 3
            + len(related_routes) * 10
            + (15 if is_entry_point else 0)
            + min(symbol_count, 10)
        )
        score = min(score, 100)

        if score >= 80:
            level = "critical"
        elif score >= 55:
            level = "high"
        elif score >= 25:
            level = "medium"
        else:
            level = "low"

        return RiskEstimate(level=level, score=score)


def analyze_change_impact(file: str) -> ImpactResponse:
    repository_path = git_clone_service.get_latest_cloned_repository()
    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)

    result = ImpactAnalyzer(repository_path, intelligence, index).analyze(file)
    result.summary = _generate_summary(result)
    return result


def _generate_summary(result: ImpactResponse) -> str | None:
    """Best-effort AI explanation of the already-computed structural impact.
    The AI layer being unavailable shouldn't fail the whole request -- the
    structural fields stand on their own."""
    evidence = {
        "file": result.file,
        "risk": result.risk.model_dump(),
        "direct_dependents": [f.path for f in result.direct_dependents],
        "indirect_dependents": [f.path for f in result.indirect_dependents],
        "related_routes": [f"{r.method} {r.path} ({r.file})" for r in result.related_routes],
        "related_frontend_files": [f"{f.path} -> {f.route} ({f.confidence} confidence)" for f in result.related_files],
    }
    user_prompt = (
        "Structural change-impact evidence (JSON, already verified by static analysis):\n\n"
        f"{json.dumps(evidence, indent=2)}"
    )

    try:
        return ai_service.complete(IMPACT_EXPLANATION_PROMPT, user_prompt)
    except AIServiceNotConfiguredError:
        return None
    except (AIRequestTimeoutError, AIServiceError) as exc:
        logger.warning("Impact AI summary failed: %s", exc)
        return None


# =====================================================================
# 12. Repository health analysis
# =====================================================================

# -- Structure -----------------------------------------------------------

LARGE_FILE_MEDIUM_LINES = 500
LARGE_FILE_HIGH_LINES = 1000
LARGE_FOLDER_FILE_COUNT = 40
DEEP_NESTING_DEPTH = 6
MAX_STRUCTURE_FINDINGS = 15

SECRET_FILE_BASENAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.test",
    "credentials.json", "secrets.json", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
SECRET_FILE_SUFFIXES = (".pem", ".key", ".pfx", ".p12")

# Auto-generated lockfiles: real line counts, but "split this file's
# responsibilities" is meaningless advice for a machine-written manifest.
LOCKFILE_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock", "go.sum",
}

# -- Dependencies ----------------------------------------------------------

# Common tooling that's configured, not imported -- flagging these as
# "unused" would be a false positive on virtually every JS/TS repo.
BUILD_ONLY_PACKAGES = {
    "vite", "eslint", "prettier", "tailwindcss", "postcss", "autoprefixer",
    "typescript", "vitest", "jest", "nodemon", "concurrently", "cross-env",
    "@vitejs/plugin-react", "@types/node", "@types/react", "@types/react-dom",
    "husky", "lint-staged", "rimraf",
}
OVERLAPPING_PACKAGE_GROUPS = [
    {"moment", "dayjs", "date-fns", "luxon"},
    {"axios", "node-fetch", "got", "superagent"},
    {"lodash", "underscore", "ramda"},
    {"redux", "mobx", "zustand", "recoil"},
    {"jest", "mocha", "ava", "vitest"},
]
MAX_UNUSED_DEP_FINDINGS = 8
MAX_PACKAGE_JSON_FILES = 5

# -- Complexity ------------------------------------------------------------

LARGE_FUNCTION_MEDIUM_LINES = 80
LARGE_FUNCTION_HIGH_LINES = 150
LARGE_CLASS_MEDIUM_LINES = 300
LARGE_CLASS_HIGH_LINES = 600
MAX_COMPLEXITY_FINDINGS = 15

# -- Architecture ------------------------------------------------------------

MAX_CYCLES_REPORTED = 5
COUPLING_MIN_THRESHOLD = 15
COUPLING_RATIO_OF_REPO = 0.3
MAX_COUPLING_FINDINGS = 5

# -- Testing -----------------------------------------------------------------

TEST_PATH_SEGMENTS = ("tests/", "__tests__/", "test/")
TEST_FILENAME_SUFFIXES = (".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx")
LOW_TEST_RATIO = 0.05
LOW_TEST_RATIO_MIN_SOURCE_FILES = 20

README_NAMES = {"readme.md", "readme", "readme.rst", "readme.txt"}
README_EMPTY_CHARS = 50
README_THIN_CHARS = 300


def _is_test_file(path: str) -> bool:
    lower = path.lower()
    if any(segment in lower for segment in TEST_PATH_SEGMENTS):
        return True
    name = posixpath.basename(lower)
    if any(name.endswith(suffix) for suffix in TEST_FILENAME_SUFFIXES):
        return True
    return name.startswith("test_") and name.endswith(".py") or (name.endswith("_test.py"))


def _is_secret_file(path: str) -> bool:
    name = posixpath.basename(path)
    if name.lower() in SECRET_FILE_BASENAMES:
        return True
    return name.lower().endswith(SECRET_FILE_SUFFIXES)


def _find_import_cycles(adjacency: dict[str, list[str]], max_cycles: int) -> list[list[str]]:
    """Standard white/gray/black DFS cycle detection over the imports-only
    file graph. Stops early once `max_cycles` are found -- a health check
    needs examples, not an exhaustive enumeration."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node: str) -> None:
        if len(cycles) >= max_cycles:
            return
        color[node] = GRAY
        path.append(node)
        for neighbor in adjacency.get(node, []):
            if len(cycles) >= max_cycles:
                break
            state = color.get(neighbor, WHITE)
            if state == WHITE:
                dfs(neighbor)
            elif state == GRAY:
                start = path.index(neighbor)
                cycles.append([*path[start:], neighbor])
        path.pop()
        color[node] = BLACK

    for node in list(adjacency.keys()):
        if len(cycles) >= max_cycles:
            break
        if color.get(node, WHITE) == WHITE:
            dfs(node)

    return cycles


class HealthAnalyzer:
    def __init__(self, repository_path: Path, day2_result, intelligence: dict, index: RelationshipIndex):
        self.repository_path = repository_path
        self.day2_result = day2_result
        self.intelligence = intelligence
        self.index = index

    def analyze(self) -> HealthResponse:
        findings: list[HealthFinding] = []

        structure_score, structure_findings = self._check_structure()
        dependency_score, dependency_findings = self._check_dependencies()
        complexity_score, complexity_findings = self._check_complexity()
        architecture_score, architecture_findings = self._check_architecture()
        documentation_score, documentation_findings = self._check_documentation()
        testing_score, testing_findings = self._check_testing()

        findings.extend(structure_findings)
        findings.extend(dependency_findings)
        findings.extend(complexity_findings)
        findings.extend(architecture_findings)
        findings.extend(documentation_findings)
        findings.extend(testing_findings)

        categories = HealthCategories(
            structure=structure_score,
            dependencies=dependency_score,
            complexity=complexity_score,
            architecture=architecture_score,
            documentation=documentation_score,
            testing=testing_score,
        )
        # Overall score is an unweighted average of the six category scores --
        # simple and easy to reason about, not a tuned/opaque formula.
        overall = round(sum(categories.model_dump().values()) / 6)

        severity_rank = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: severity_rank[f.severity])

        return HealthResponse(score=overall, categories=categories, findings=findings)

    # -- Structure -----------------------------------------------------------

    def _check_structure(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        for entry in self.day2_result.files:
            lines = entry["lines"]
            # "Other"-language files are data/config/lockfiles, not source
            # code -- flagging a CSV or lockfile as needing to be "split"
            # isn't meaningful engineering advice. Nesting depth still
            # applies to any file, source or not.
            is_scoreable_source = entry["language"] != "Other" and posixpath.basename(entry["path"]) not in LOCKFILE_BASENAMES

            if is_scoreable_source and lines >= LARGE_FILE_HIGH_LINES:
                score -= 6
                findings.append(
                    HealthFinding(
                        severity="high",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is {lines} lines long.",
                        recommendation="Consider splitting this file's responsibilities into smaller modules.",
                    )
                )
            elif is_scoreable_source and lines >= LARGE_FILE_MEDIUM_LINES:
                score -= 3
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is {lines} lines long.",
                        recommendation="Consider splitting this file if it covers more than one responsibility.",
                    )
                )

            if entry["path"].count("/") > DEEP_NESTING_DEPTH:
                score -= 2
                findings.append(
                    HealthFinding(
                        severity="low",
                        category="structure",
                        path=entry["path"],
                        reason=f"{entry['path']} is nested {entry['path'].count('/')} folders deep.",
                        recommendation="Deeply nested folder structures can be harder to navigate; consider flattening if not intentional.",
                    )
                )

        folder_counts: dict[str, int] = {}
        for entry in self.day2_result.files:
            folder = posixpath.dirname(entry["path"]) or "."
            folder_counts[folder] = folder_counts.get(folder, 0) + 1
        for folder, count in folder_counts.items():
            if count > LARGE_FOLDER_FILE_COUNT:
                score -= 5
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="structure",
                        path=folder,
                        reason=f"{folder} contains {count} files directly.",
                        recommendation="Consider organizing this folder into subfolders by feature or responsibility.",
                    )
                )

        secret_files = [entry["path"] for entry in self.day2_result.files if _is_secret_file(entry["path"])]
        for path in secret_files:
            findings.append(
                HealthFinding(
                    severity="low",
                    category="structure",
                    path=path,
                    reason="Environment configuration or credential-shaped file detected. Its contents were not read or analyzed.",
                    recommendation="Ensure this file is excluded from version control and never shared or exported.",
                )
            )

        return max(score, 0), findings[:MAX_STRUCTURE_FINDINGS]

    # -- Dependencies ----------------------------------------------------------

    def _check_dependencies(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        files_by_path = {f["path"]: f for f in self.intelligence["files"]}
        used_packages: set[str] = set()
        for imp in self.intelligence["imports"]:
            if not imp["is_external"]:
                continue
            language = files_by_path.get(imp["file"], {}).get("language", "")
            used_packages.add(external_package_name(imp["source"], language))

        package_json_paths = [f["path"] for f in self.day2_result.files if posixpath.basename(f["path"]) == "package.json"]
        all_declared: dict[str, str] = {}  # package name -> the package.json path it was declared in

        for rel_path in package_json_paths[:MAX_PACKAGE_JSON_FILES]:
            try:
                data = json.loads((self.repository_path / rel_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            declared = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for package_name in declared:
                all_declared.setdefault(package_name, rel_path)
                if package_name in BUILD_ONLY_PACKAGES or package_name in used_packages:
                    continue
                score -= 5
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="dependencies",
                        path=rel_path,
                        reason=f"'{package_name}' is declared in {rel_path} but no import of it was found in the analyzed source.",
                        recommendation=f"Verify whether '{package_name}' is still needed; if not, remove it.",
                    )
                )

        declared_names = set(all_declared.keys())
        for group in OVERLAPPING_PACKAGE_GROUPS:
            overlap = group & declared_names
            if len(overlap) > 1:
                score -= 8
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="dependencies",
                        path=None,
                        reason=f"Multiple overlapping packages are declared for the same purpose: {', '.join(sorted(overlap))}.",
                        recommendation="Consider standardizing on a single package to reduce bundle size and maintenance overhead.",
                    )
                )

        return max(score, 0), findings[:MAX_UNUSED_DEP_FINDINGS]

    # -- Complexity ------------------------------------------------------------

    def _check_complexity(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        for symbol in self.intelligence["symbols"]:
            length = symbol["end_line"] - symbol["start_line"] + 1
            if symbol["kind"] == "function":
                if length >= LARGE_FUNCTION_HIGH_LINES:
                    score -= 4
                    findings.append(
                        HealthFinding(
                            severity="high",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Function `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider breaking this function into smaller, single-purpose functions.",
                        )
                    )
                elif length >= LARGE_FUNCTION_MEDIUM_LINES:
                    score -= 2
                    findings.append(
                        HealthFinding(
                            severity="medium",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Function `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider whether this function can be simplified or split.",
                        )
                    )
            elif symbol["kind"] == "class":
                if length >= LARGE_CLASS_HIGH_LINES:
                    score -= 5
                    findings.append(
                        HealthFinding(
                            severity="high",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Class `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider splitting this class's responsibilities into smaller classes/modules.",
                        )
                    )
                elif length >= LARGE_CLASS_MEDIUM_LINES:
                    score -= 3
                    findings.append(
                        HealthFinding(
                            severity="medium",
                            category="complexity",
                            path=symbol["file"],
                            reason=f"Class `{symbol['name']}` in {symbol['file']} is {length} lines long.",
                            recommendation="Consider whether this class covers more than one responsibility.",
                        )
                    )

        return max(score, 0), findings[:MAX_COMPLEXITY_FINDINGS]

    # -- Architecture ------------------------------------------------------------

    def _check_architecture(self) -> tuple[int, list[HealthFinding]]:
        score = 100
        findings: list[HealthFinding] = []

        adjacency: dict[str, list[str]] = {}
        for (source, target, edge_type) in self.index.file_edges:
            if edge_type == "imports":
                adjacency.setdefault(source, []).append(target)

        cycles = _find_import_cycles(adjacency, MAX_CYCLES_REPORTED)
        for cycle in cycles:
            score -= 15
            findings.append(
                HealthFinding(
                    severity="high",
                    category="architecture",
                    path=cycle[0],
                    reason=f"Circular import detected: {' -> '.join(cycle)}.",
                    recommendation="Consider restructuring these modules to break the cycle, e.g. extracting shared code to a separate module.",
                )
            )

        total_files = len(self.index.file_paths)
        threshold = max(COUPLING_MIN_THRESHOLD, int(total_files * COUPLING_RATIO_OF_REPO))
        coupling_findings = 0
        for path in self.index.file_paths:
            if coupling_findings >= MAX_COUPLING_FINDINGS:
                break
            fan_in = len(self.index.reverse(path))
            fan_out = len(self.index.forward(path))
            if fan_in > threshold or fan_out > threshold:
                score -= 5
                coupling_findings += 1
                findings.append(
                    HealthFinding(
                        severity="medium",
                        category="architecture",
                        path=path,
                        reason=f"{path} is connected to {fan_in} file(s) that depend on it and {fan_out} file(s) it depends on -- unusually high for this repository's size.",
                        recommendation="High coupling can make changes riskier; consider whether responsibilities can be separated.",
                    )
                )

        return max(score, 0), findings

    # -- Documentation ------------------------------------------------------------

    def _check_documentation(self) -> tuple[int, list[HealthFinding]]:
        readme_path = next(
            (f["path"] for f in self.day2_result.files if "/" not in f["path"] and f["path"].lower() in README_NAMES),
            None,
        )

        if not readme_path:
            return 60, [
                HealthFinding(
                    severity="high",
                    category="documentation",
                    path=None,
                    reason="No README file was found at the repository root.",
                    recommendation="Add a README describing what the project does, how to run it, and its architecture.",
                )
            ]

        try:
            content = (self.repository_path / readme_path).read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            content = ""

        if len(content) < README_EMPTY_CHARS:
            return 70, [
                HealthFinding(
                    severity="medium",
                    category="documentation",
                    path=readme_path,
                    reason=f"{readme_path} exists but appears to be empty or a placeholder ({len(content)} characters).",
                    recommendation="Expand the README with a project description, setup instructions, and usage examples.",
                )
            ]

        if len(content) < README_THIN_CHARS:
            return 85, [
                HealthFinding(
                    severity="low",
                    category="documentation",
                    path=readme_path,
                    reason=f"{readme_path} is quite short ({len(content)} characters).",
                    recommendation="Consider expanding setup, usage, and architecture notes.",
                )
            ]

        return 100, []

    # -- Testing -----------------------------------------------------------------

    def _check_testing(self) -> tuple[int, list[HealthFinding]]:
        test_files = [f["path"] for f in self.day2_result.files if _is_test_file(f["path"])]
        total_source_files = sum(self.day2_result.languages.values())

        if not test_files:
            return 50, [
                HealthFinding(
                    severity="high",
                    category="testing",
                    path=None,
                    reason="No test files were detected in this repository.",
                    recommendation="Consider adding tests for the most important application logic.",
                )
            ]

        if total_source_files >= LOW_TEST_RATIO_MIN_SOURCE_FILES:
            ratio = len(test_files) / total_source_files
            if ratio < LOW_TEST_RATIO:
                return 85, [
                    HealthFinding(
                        severity="medium",
                        category="testing",
                        path=None,
                        reason=(
                            f"Only {len(test_files)} test file(s) were detected out of {total_source_files} "
                            "source files -- a low file-count ratio for a repository this size."
                        ),
                        recommendation="Consider adding tests for additional modules, especially core business logic.",
                    )
                ]

        return 100, []


def analyze_repository_health() -> HealthResponse:
    repository_path = git_clone_service.get_latest_cloned_repository()
    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)
    return HealthAnalyzer(repository_path, day2_result, intelligence, index).analyze()


# =====================================================================
# 13. Public response models + this module's public interface
# =====================================================================

# -- Code intelligence ---------------------------------------------


class RepositoryInfo(BaseModel):
    name: str
    languages: list[str]
    frameworks: list[str]


class FileEntry(BaseModel):
    path: str
    language: str
    functions_count: int
    classes_count: int
    imports_count: int
    exports_count: int
    parse_error: str | None


class SymbolEntry(BaseModel):
    kind: str
    name: str
    file: str
    start_line: int
    end_line: int
    parameters: list[str]
    is_method: bool
    class_name: str | None
    methods: list[str]


class ImportEntry(BaseModel):
    file: str
    source: str
    imported_names: list[str]
    is_default: bool
    resolved_target: str | None
    is_external: bool
    line: int


class ExportEntry(BaseModel):
    file: str
    name: str
    kind: str
    line: int


class RelationshipEntry(BaseModel):
    source: str
    target: str | None
    type: str
    resolved: bool
    raw_callee: str | None


class RouteEntry(BaseModel):
    method: str
    path: str
    handler: str
    file: str
    line: int


class ParseStats(BaseModel):
    files_parsed: int
    files_skipped: int
    parse_errors: int


class CodeIntelligenceResponse(BaseModel):
    repository: RepositoryInfo
    files: list[FileEntry]
    symbols: list[SymbolEntry]
    imports: list[ImportEntry]
    exports: list[ExportEntry]
    relationships: list[RelationshipEntry]
    routes: list[RouteEntry]
    stats: ParseStats


class CodeAnalysisSummaryResponse(BaseModel):
    status: str
    files_parsed: int
    files_skipped: int
    parse_errors: int
    functions_found: int
    classes_found: int
    imports_found: int
    relationships_found: int
    routes_found: int

# -- Graph ------------------------------------------------------------

NodeType = Literal["file", "folder", "external"]
EdgeType = Literal["imports", "calls"]


class GraphNodeData(BaseModel):
    label: str
    path: str | None = None
    language: str | None = None
    lines: int | None = None
    functions: int | None = None
    classes: int | None = None
    imports: int | None = None
    exports: int | None = None
    layer: str | None = None
    file_count: int | None = None
    parse_error: str | None = None


class GraphNode(BaseModel):
    id: str
    type: NodeType
    data: GraphNodeData


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: EdgeType
    weight: int = 1


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    mode: Literal["files", "folders"]
    truncated: bool
    # Files with a parseable relationship (imports/calls) that this
    # particular graph query is scoped to -- NOT the repository's total file
    # count. That's `AnalysisResponse.total_files` / `RepositoryTreeResponse
    # .total_files`, the canonical repository-wide number; this field only
    # describes the (necessarily partial) relationship graph itself.
    analyzed_file_count: int
    message: str | None = None

# -- Impact analysis ---------------------------------------------------

RiskLevel = Literal["low", "medium", "high", "critical"]
Confidence = Literal["high", "medium", "low", "unknown"]
DependencyType = Literal["imports", "calls"]


class ImpactedFile(BaseModel):
    path: str
    depth: int
    via: list[DependencyType]
    discovered_via: str  # the file this dependent was reached through, for drawing the actual chain


class RelatedRoute(BaseModel):
    method: str
    path: str
    file: str


class RelatedFile(BaseModel):
    path: str
    route: str
    confidence: Confidence


class RiskEstimate(BaseModel):
    level: RiskLevel
    score: int


class ImpactRequest(BaseModel):
    file: str


class ImpactResponse(BaseModel):
    file: str
    risk: RiskEstimate
    direct_dependents: list[ImpactedFile]
    indirect_dependents: list[ImpactedFile]
    related_routes: list[RelatedRoute]
    related_files: list[RelatedFile]
    truncated: bool
    summary: str | None = None

# -- Health -------------------------------------------------------------

Severity = Literal["low", "medium", "high"]
HealthCategoryName = Literal["structure", "dependencies", "complexity", "architecture", "documentation", "testing"]


class HealthFinding(BaseModel):
    severity: Severity
    category: HealthCategoryName
    path: str | None = None
    reason: str
    recommendation: str


class HealthCategories(BaseModel):
    structure: int
    dependencies: int
    complexity: int
    architecture: int
    documentation: int
    testing: int


class HealthResponse(BaseModel):
    score: int
    categories: HealthCategories
    findings: list[HealthFinding]


# -- Public interface ---------------------------------------------------
# Everything else in this file is an implementation detail of the names
# below -- api.py and the test suite are the only external consumers, and
# only ever import from this list. Grouped by section; see the module
# docstring for what each does.
__all__ = [
    # 1-6: parsers + resolver -- exercised directly by parser unit tests,
    # and used internally by CodeIntelligenceAnalyzer.
    "BaseParser",
    "ParseError",
    "PythonParser",
    "JavaScriptParser",
    "TypeScriptParser",
    "ParserFactory",
    "parser_factory",
    "LocalDependencyResolver",
    # 7-8: code intelligence construction + caching
    "CodeIntelligenceAnalyzer",
    "CodeIntelligenceResult",
    "analysis_storage",
    "run_and_store_code_intelligence",
    "get_or_build_code_intelligence",
    # 9-12: relationship analysis, architecture graph, impact, health
    "RelationshipIndex",
    "GraphBuilder",
    "build_repository_graph",
    "ImpactAnalyzer",
    "ImpactAnalyzerError",
    "analyze_change_impact",
    "HealthAnalyzer",
    "analyze_repository_health",
    # 13: response models declared as api.py routes' response_model=
    "CodeAnalysisSummaryResponse",
    "CodeIntelligenceResponse",
    "GraphResponse",
    "ImpactRequest",
    "ImpactResponse",
    "HealthResponse",
]
