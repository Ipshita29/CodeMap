from dataclasses import asdict, dataclass
from pathlib import Path

from app.analyzer.file_scanner import FileRecord, FileScanner
from app.analyzer.folder_tree import TreeNode, build_repository_tree
from app.analyzer.tech_stack_detector import TechStackDetector
from app.utils.exceptions import RepositoryAnalysisError


@dataclass
class AnalysisResult:
    repository_name: str
    total_files: int
    total_folders: int
    languages: dict[str, int]
    frameworks: list[str]
    repository_tree: list[TreeNode]
    statistics: dict
    files: list[dict]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["repository_tree"] = [node.to_dict() for node in self.repository_tree]
        return data


class RepositoryAnalyzer:
    """Scans a cloned repository and produces structured, deterministic metadata.

    No AI/LLM involved — this is the shared foundation every future CodeMap
    feature (chat, summaries, architecture diagrams, dependency graphs,
    health scoring) reads from, so its output shape is meant to stay stable
    even as those features are added on top.
    """

    def __init__(self, repository_path: Path):
        self.repository_path = Path(repository_path)
        if not self.repository_path.is_dir():
            raise RepositoryAnalysisError(f"Repository path does not exist: {repository_path}")

    def analyze(self) -> AnalysisResult:
        try:
            file_records = FileScanner(self.repository_path).scan()
        except OSError as exc:
            raise RepositoryAnalysisError(f"Failed to scan repository: {exc}") from exc

        file_paths = [record.path for record in file_records]
        repository_tree, total_folders = build_repository_tree(file_paths)
        frameworks = TechStackDetector(self.repository_path, file_paths).detect()

        return AnalysisResult(
            repository_name=self.repository_path.name,
            total_files=len(file_records),
            total_folders=total_folders,
            languages=self._count_languages(file_records),
            frameworks=frameworks,
            repository_tree=repository_tree,
            statistics=self._build_statistics(file_records),
            files=[asdict(record) for record in file_records],
        )

    @staticmethod
    def _count_languages(records: list[FileRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            if record.language == "Other":
                continue
            counts[record.language] = counts.get(record.language, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))

    @staticmethod
    def _build_statistics(records: list[FileRecord]) -> dict:
        total_lines = sum(record.lines for record in records)
        largest_file = max(records, key=lambda record: record.size_bytes, default=None)

        return {
            "total_lines": total_lines,
            "largest_file": (
                {
                    "path": largest_file.path,
                    "size_bytes": largest_file.size_bytes,
                    "lines": largest_file.lines,
                }
                if largest_file
                else None
            ),
        }
