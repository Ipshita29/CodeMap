from pathlib import Path

import tree_sitter_python as tspy
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
