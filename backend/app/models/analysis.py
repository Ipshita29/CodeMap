from typing import Any

from pydantic import BaseModel


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
    folder_tree: dict[str, Any]
    statistics: Statistics
    files: list[FileEntry]
