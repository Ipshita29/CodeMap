from fastapi import APIRouter, HTTPException

from app.health.health_models import HealthResponse
from app.health.health_service import analyze_repository_health
from app.utils.exceptions import NoRepositoryImportedError, RepositoryAnalysisError

router = APIRouter(prefix="/repository", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_repository_health() -> HealthResponse:
    try:
        return analyze_repository_health()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
