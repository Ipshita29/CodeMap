from pydantic import BaseModel


class RepositoryTreeNode(BaseModel):
    name: str
    type: str  # "file" | "directory"
    path: str
    children: list["RepositoryTreeNode"] | None = None


class LargestFile(BaseModel):
    path: str
    size_bytes: int
    lines: int


class Statistics(BaseModel):
    total_lines: int
    largest_file: LargestFile | None


class FileEntry(BaseModel):
    path: str
    extension: str
    language: str
    size_bytes: int
    lines: int
    imports: list[str]


class AnalysisResponse(BaseModel):
    repository_name: str
    total_files: int
    total_folders: int
    languages: dict[str, int]
    frameworks: list[str]
    repository_tree: list[RepositoryTreeNode]
    statistics: Statistics
    files: list[FileEntry]


class RepositoryTreeResponse(BaseModel):
    """The same repository_tree/total_files/total_folders AnalysisResponse
    carries, exposed on its own so the Architecture Repository Map can fetch
    just the tree without pulling the full per-file payload."""

    tree: list[RepositoryTreeNode]
    total_files: int
    total_folders: int
