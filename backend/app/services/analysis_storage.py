import json
from pathlib import Path

from app.analyzer.code_intelligence import CodeIntelligenceResult
from app.config.settings import settings

REPOSITORY_FILE = "repository.json"
CODE_STRUCTURE_FILE = "code_structure.json"
RELATIONSHIPS_FILE = "relationships.json"


class AnalysisStorage:
    """Persists a CodeIntelligenceResult as JSON, split into three files
    rather than one deeply nested blob, per the Day 3 brief. This is a
    deliberately temporary storage layer — no database yet — but the split
    (repository/file-level facts, code structure, relationship graph) maps
    directly onto what would become separate tables if this moves to
    Postgres later, so today's shape isn't a dead end.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or settings.analysis_output_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, repository_id: str, result: CodeIntelligenceResult) -> Path:
        data = result.to_dict()
        repo_dir = self.base_dir / repository_id
        repo_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(
            repo_dir / REPOSITORY_FILE,
            {"repository": data["repository"], "files": data["files"], "stats": data["stats"]},
        )
        self._write_json(
            repo_dir / CODE_STRUCTURE_FILE,
            {
                "symbols": data["symbols"],
                "imports": data["imports"],
                "exports": data["exports"],
                "routes": data["routes"],
            },
        )
        self._write_json(repo_dir / RELATIONSHIPS_FILE, {"relationships": data["relationships"]})
        return repo_dir

    def load(self, repository_id: str) -> dict | None:
        repo_dir = self.base_dir / repository_id
        paths = [repo_dir / name for name in (REPOSITORY_FILE, CODE_STRUCTURE_FILE, RELATIONSHIPS_FILE)]
        if not all(path.exists() for path in paths):
            return None

        repository_data, code_structure_data, relationships_data = (self._read_json(path) for path in paths)

        return {
            **repository_data,
            **code_structure_data,
            **relationships_data,
        }

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


analysis_storage = AnalysisStorage()
