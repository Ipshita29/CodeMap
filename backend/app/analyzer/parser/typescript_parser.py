import tree_sitter_typescript as tsts
from tree_sitter import Language

from app.analyzer.parser.javascript_parser import JavaScriptParser


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
