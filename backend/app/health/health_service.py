from app.graph.relationship_index import RelationshipIndex
from app.health.health_analyzer import HealthAnalyzer
from app.health.health_models import HealthResponse
from app.services.code_intelligence_service import get_or_build_code_intelligence
from app.services.git_service import git_service
from app.services.repository_snapshot import get_repository_snapshot


def analyze_repository_health() -> HealthResponse:
    repository_path = git_service.get_latest_cloned_repository()
    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)
    return HealthAnalyzer(repository_path, day2_result, intelligence, index).analyze()
