import json
import logging

from app.ai.ai_service import ai_service
from app.ai.prompts import IMPACT_EXPLANATION_PROMPT
from app.graph.relationship_index import RelationshipIndex
from app.impact.impact_analyzer import ImpactAnalyzer, ImpactAnalyzerError
from app.impact.impact_models import ImpactResponse
from app.services.code_intelligence_service import get_or_build_code_intelligence
from app.services.git_service import git_service
from app.services.repository_snapshot import get_repository_snapshot
from app.utils.exceptions import AIRequestTimeoutError, AIServiceError, AIServiceNotConfiguredError

logger = logging.getLogger(__name__)


def analyze_change_impact(file: str) -> ImpactResponse:
    repository_path = git_service.get_latest_cloned_repository()
    day2_result = get_repository_snapshot(repository_path)
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    index = RelationshipIndex(intelligence)

    result = ImpactAnalyzer(repository_path, intelligence, index).analyze(file)
    result.summary = _generate_summary(result)
    return result


def _generate_summary(result: ImpactResponse) -> str | None:
    """Best-effort AI explanation of the already-computed structural impact.
    The AI layer being unavailable shouldn't fail the whole request -- the
    structural fields stand on their own."""
    evidence = {
        "file": result.file,
        "risk": result.risk.model_dump(),
        "direct_dependents": [f.path for f in result.direct_dependents],
        "indirect_dependents": [f.path for f in result.indirect_dependents],
        "related_routes": [f"{r.method} {r.path} ({r.file})" for r in result.related_routes],
        "related_frontend_files": [f"{f.path} -> {f.route} ({f.confidence} confidence)" for f in result.related_files],
    }
    user_prompt = (
        "Structural change-impact evidence (JSON, already verified by static analysis):\n\n"
        f"{json.dumps(evidence, indent=2)}"
    )

    try:
        return ai_service.complete(IMPACT_EXPLANATION_PROMPT, user_prompt)
    except AIServiceNotConfiguredError:
        return None
    except (AIRequestTimeoutError, AIServiceError) as exc:
        logger.warning("Impact AI summary failed: %s", exc)
        return None


__all__ = ["analyze_change_impact", "ImpactAnalyzerError"]
