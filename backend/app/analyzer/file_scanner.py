import os
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzer.constants import BINARY_EXTENSIONS, IGNORED_DIRS, LANGUAGE_EXTENSIONS
from app.analyzer.import_extractor import ImportExtractor


@dataclass
class FileRecord:
    path: str
    extension: str
    language: str
    size_bytes: int
    lines: int
    imports: list[str] = field(default_factory=list)


class FileScanner:
    """Recursively scans a repository and extracts per-file metadata.

    Walks with `os.walk` and prunes ignored directory names *before*
    descending into them, so a huge `node_modules` or `.git` tree is never
    actually traversed — this is what keeps the scan cheap on real repos.
    """

    def __init__(self, root: Path):
        self.root = root

    def scan(self) -> list[FileRecord]:
        records: list[FileRecord] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
            for filename in filenames:
                records.append(self._build_record(Path(dirpath) / filename))
        return records

    def _build_record(self, path: Path) -> FileRecord:
        relative = path.relative_to(self.root).as_posix()
        extension = path.suffix
        language = LANGUAGE_EXTENSIONS.get(extension, "Other")
        size_bytes = self._safe_size(path)

        content = None if extension in BINARY_EXTENSIONS else self._read_text(path)
        lines = len(content.splitlines()) if content else 0
        imports = ImportExtractor.extract(content, extension) if content else []

        return FileRecord(
            path=relative,
            extension=extension,
            language=language,
            size_bytes=size_bytes,
            lines=lines,
            imports=imports,
        )

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
