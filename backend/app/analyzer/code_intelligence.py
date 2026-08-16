import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.analyzer.parser.base_parser import CallInfo, FunctionInfo, ParsedFile, ParseError, symbol_id
from app.analyzer.parser.parser_factory import parser_factory
from app.analyzer.repository_analyzer import AnalysisResult
from app.analyzer.resolver import LocalDependencyResolver

logger = logging.getLogger(__name__)


@dataclass
class ParseStats:
    files_parsed: int = 0
    files_skipped: int = 0
    parse_errors: int = 0


@dataclass
class SymbolEntry:
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
class ImportEntry:
    file: str
    source: str
    imported_names: list[str]
    is_default: bool
    resolved_target: str | None
    is_external: bool
    line: int


@dataclass
class ExportEntry:
    file: str
    name: str
    kind: str
    line: int


@dataclass
class RelationshipEntry:
    source: str
    target: str | None
    type: str  # "imports" | "contains" | "calls"
    resolved: bool = True
    raw_callee: str | None = None


@dataclass
class RouteEntry:
    method: str
    path: str
    handler: str
    file: str
    line: int


@dataclass
class FileEntry:
    path: str
    language: str
    functions_count: int = 0
    classes_count: int = 0
    imports_count: int = 0
    exports_count: int = 0
    parse_error: str | None = None


@dataclass
class RepositoryInfo:
    name: str
    languages: list[str]
    frameworks: list[str]


@dataclass
class CodeIntelligenceResult:
    repository: RepositoryInfo
    files: list[FileEntry]
    symbols: list[SymbolEntry]
    imports: list[ImportEntry]
    exports: list[ExportEntry]
    relationships: list[RelationshipEntry]
    routes: list[RouteEntry]
    stats: ParseStats

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
        stats = ParseStats()
        parsed_files: dict[str, ParsedFile] = {}
        file_entries: list[FileEntry] = []
        all_paths = [entry["path"] for entry in self.day2_result.files]

        for entry in self.day2_result.files:
            path, extension, language = entry["path"], entry["extension"], entry["language"]
            parser = parser_factory.get_parser(extension)
            if parser is None:
                continue

            if entry["size_bytes"] > self.max_file_size_bytes:
                stats.files_skipped += 1
                file_entries.append(FileEntry(path=path, language=language, parse_error="skipped: exceeds max file size"))
                continue

            try:
                parsed = parser.parse(self.repository_path / path, path)
            except ParseError as exc:
                stats.parse_errors += 1
                logger.warning("Failed to parse %s: %s", path, exc)
                file_entries.append(FileEntry(path=path, language=language, parse_error=str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - a single bad file must never abort the repo scan
                stats.parse_errors += 1
                logger.warning("Unexpected error parsing %s: %s", path, exc)
                file_entries.append(FileEntry(path=path, language=language, parse_error=str(exc)))
                continue

            stats.files_parsed += 1
            parsed_files[path] = parsed
            file_entries.append(
                FileEntry(
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

        symbols: list[SymbolEntry] = []
        imports: list[ImportEntry] = []
        exports: list[ExportEntry] = []
        relationships: list[RelationshipEntry] = []
        routes: list[RouteEntry] = []
        local_import_targets: dict[str, dict[str, str]] = {}

        for path, parsed in parsed_files.items():
            for fn in parsed.functions:
                symbols.append(
                    SymbolEntry(
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
                relationships.append(RelationshipEntry(source=path, target=symbol_id(path, fn.name), type="contains"))

            for cls in parsed.classes:
                symbols.append(
                    SymbolEntry(
                        kind="class",
                        name=cls.name,
                        file=cls.file,
                        start_line=cls.start_line,
                        end_line=cls.end_line,
                        methods=cls.methods,
                    )
                )
                relationships.append(RelationshipEntry(source=path, target=symbol_id(path, cls.name), type="contains"))

            for imp in parsed.imports:
                entry, import_rels = self._resolve_import(path, imp, parsed.language, resolver)
                imports.append(entry)
                relationships.extend(import_rels)
                if entry.resolved_target and imp.imported_names:
                    bucket = local_import_targets.setdefault(path, {})
                    for name in imp.imported_names:
                        bucket[name] = entry.resolved_target

            for exp in parsed.exports:
                exports.append(ExportEntry(file=exp.file, name=exp.name, kind=exp.kind, line=exp.line))

            for route in parsed.routes:
                routes.append(RouteEntry(method=route.method, path=route.path, handler=route.handler, file=route.file, line=route.line))

        for path, parsed in parsed_files.items():
            for call in parsed.calls:
                relationship = self._resolve_call(
                    path, call, parsed.language, function_index, method_index, class_index, local_import_targets
                )
                if relationship is not None:
                    relationships.append(relationship)

        repository_info = RepositoryInfo(
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
    ) -> tuple[ImportEntry, list[RelationshipEntry]]:
        relationships: list[RelationshipEntry] = []

        if language == "Python" and imp.source.lstrip(".") == "" and imp.imported_names:
            # `from . import a, b` -- each name is its own sibling module,
            # so there's no single resolved_target for the statement itself.
            resolved_target = None
            for name in imp.imported_names:
                resolved = resolver.resolve_python_relative_name(path, imp.source, name)
                if resolved.target:
                    resolved_target = resolved_target or resolved.target
                    relationships.append(RelationshipEntry(source=path, target=resolved.target, type="imports"))
            entry = ImportEntry(
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

        entry = ImportEntry(
            file=path,
            source=imp.source,
            imported_names=imp.imported_names,
            is_default=imp.is_default,
            resolved_target=resolved.target,
            is_external=resolved.is_external,
            line=imp.line,
        )
        if resolved.target:
            relationships.append(RelationshipEntry(source=path, target=resolved.target, type="imports"))
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
    ) -> RelationshipEntry | None:
        if not call.caller_name:
            return None  # nothing to attach an unattributed top-level call to
        caller_symbol = symbol_id(path, call.caller_name)

        if not call.is_member_call:
            callee_name = call.callee_raw

            if (path, callee_name) in function_index or (path, callee_name) in class_index:
                return RelationshipEntry(source=caller_symbol, target=symbol_id(path, callee_name), type="calls")

            target_file = local_import_targets.get(path, {}).get(callee_name)
            if target_file and ((target_file, callee_name) in function_index or (target_file, callee_name) in class_index):
                return RelationshipEntry(source=caller_symbol, target=symbol_id(target_file, callee_name), type="calls")

        elif language == "Python" and call.callee_raw.startswith("self.") and call.caller_class:
            method_name = call.callee_raw.split(".", 1)[1]
            if (path, call.caller_class, method_name) in method_index:
                return RelationshipEntry(source=caller_symbol, target=symbol_id(path, method_name), type="calls")

        return RelationshipEntry(source=caller_symbol, target=None, type="calls", resolved=False, raw_callee=call.callee_raw)
