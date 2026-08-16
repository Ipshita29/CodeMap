from pathlib import Path

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Node, Parser

from app.analyzer.parser.base_parser import (
    BaseParser,
    CallInfo,
    ClassInfo,
    ExportInfo,
    FunctionInfo,
    ImportInfo,
    ParsedFile,
    ParseError,
    RouteInfo,
)

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
