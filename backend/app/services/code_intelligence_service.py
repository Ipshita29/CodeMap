from pathlib import Path

from app.analyzer.code_intelligence import CodeIntelligenceAnalyzer, CodeIntelligenceResult
from app.analyzer.repository_analyzer import AnalysisResult, RepositoryAnalyzer
from app.config.settings import settings
from app.services.analysis_storage import analysis_storage


def run_and_store_code_intelligence(
    repository_path: Path, day2_result: AnalysisResult | None = None
) -> CodeIntelligenceResult:
    """Runs the Day 2 + Day 3 analysis pipeline and persists the result.

    `day2_result` can be passed in when the caller already computed it
    (e.g. the context builder, which also needs it for repository metadata)
    to avoid scanning the repository twice.
    """
    if day2_result is None:
        day2_result = RepositoryAnalyzer(repository_path).analyze()

    intelligence = CodeIntelligenceAnalyzer(
        repository_path, day2_result, settings.max_parseable_file_size_bytes
    ).analyze()
    analysis_storage.save(repository_path.name, intelligence)
    return intelligence


def get_or_build_code_intelligence(repository_path: Path, day2_result: AnalysisResult | None = None) -> dict:
    """Returns the stored code intelligence analysis, building it on demand
    if `POST /repository/analyze-code` hasn't been run yet — the AI layer
    shouldn't require the user to have visited the debug view first."""
    data = analysis_storage.load(repository_path.name)
    if data is not None:
        return data
    return run_and_store_code_intelligence(repository_path, day2_result).to_dict()
