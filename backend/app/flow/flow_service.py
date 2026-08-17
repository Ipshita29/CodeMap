from app.analyzer.repository_analyzer import RepositoryAnalyzer
from app.flow.flow_analyzer import FlowAnalyzer, FlowAnalyzerError
from app.flow.flow_models import FlowResponse
from app.graph.relationship_index import RelationshipIndex
from app.services.code_intelligence_service import get_or_build_code_intelligence
from app.services.git_service import git_service


def trace_execution_flow(start_file: str | None, start_function: str | None, query: str | None) -> FlowResponse:
    repository_path = git_service.get_latest_cloned_repository()
    day2_result = RepositoryAnalyzer(repository_path).analyze()
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)
    analyzer = FlowAnalyzer(repository_path, intelligence, index)

    resolved_start_file = start_file
    if not resolved_start_file:
        if not query:
            raise FlowAnalyzerError("Provide either 'start_file' or 'query' to trace a flow.")
        resolved_start_file = analyzer.resolve_start_file(query)
        if not resolved_start_file:
            raise FlowAnalyzerError(
                f"Could not confidently identify a starting point for '{query}'. Try selecting a specific file instead."
            )

    return analyzer.analyze(resolved_start_file, start_function)
