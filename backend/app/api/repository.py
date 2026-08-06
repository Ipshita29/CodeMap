from fastapi import APIRouter, HTTPException

from app.analyzer.repository_analyzer import RepositoryAnalyzer
from app.models.analysis import AnalysisResponse
from app.models.repository import RepositoryImportRequest, RepositoryImportResponse
from app.services.git_service import git_service
from app.utils.exceptions import (
    InvalidGitHubURLError,
    NoRepositoryImportedError,
    RepositoryAnalysisError,
    RepositoryCloneError,
)
from app.utils.validators import validate_github_url

router = APIRouter(prefix="/repository", tags=["repository"])


@router.post("/import", response_model=RepositoryImportResponse)
def import_repository(payload: RepositoryImportRequest) -> RepositoryImportResponse:
    try:
        repo_name = validate_github_url(payload.github_url)
    except InvalidGitHubURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        clone_path = git_service.clone_repository(payload.github_url, repo_name)
    except RepositoryCloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RepositoryImportResponse(
        repository_name=repo_name,
        clone_path=str(clone_path),
        status="success",
    )


@router.get("/analyze", response_model=AnalysisResponse)
def analyze_repository() -> AnalysisResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = RepositoryAnalyzer(repository_path).analyze()
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AnalysisResponse(**result.to_dict())
