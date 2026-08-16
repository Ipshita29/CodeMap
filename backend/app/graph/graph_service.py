from app.analyzer.repository_analyzer import RepositoryAnalyzer
from app.config.settings import settings
from app.graph.graph_builder import GraphBuilder
from app.models.graph import GraphResponse
from app.services.code_intelligence_service import get_or_build_code_intelligence
from app.services.git_service import git_service


def build_repository_graph(focus: str | None = None) -> GraphResponse:
    """Builds the repository graph from the existing Day 2/3 analysis --
    reruns the (cheap, filesystem-only) Day 2 scan and reuses stored Day 3
    code intelligence if it's already been computed, exactly like the AI
    endpoints do, so visiting the graph doesn't require a separate manual
    analysis step."""
    repository_path = git_service.get_latest_cloned_repository()
    day2_result = RepositoryAnalyzer(repository_path).analyze()
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    builder = GraphBuilder(day2_result.files, intelligence, settings.graph_max_file_nodes)
    return builder.build(focus=focus)
