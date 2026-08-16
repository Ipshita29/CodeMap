from app.analyzer.parser.base_parser import BaseParser
from app.analyzer.parser.javascript_parser import JavaScriptParser
from app.analyzer.parser.python_parser import PythonParser
from app.analyzer.parser.typescript_parser import TypeScriptParser


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
