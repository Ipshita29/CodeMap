from pydantic import BaseModel


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
