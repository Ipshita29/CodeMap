from fastapi import APIRouter, HTTPException

from app.analyzer.repository_analyzer import RepositoryAnalyzer
from app.graph.graph_service import build_repository_graph
from app.models.analysis import AnalysisResponse
from app.models.code_intelligence import CodeAnalysisSummaryResponse, CodeIntelligenceResponse
from app.models.graph import GraphResponse
from app.models.repository import RepositoryImportRequest, RepositoryImportResponse
from app.services.analysis_storage import analysis_storage
from app.services.code_intelligence_service import run_and_store_code_intelligence
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


@router.post("/analyze-code", response_model=CodeAnalysisSummaryResponse)
def analyze_code() -> CodeAnalysisSummaryResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        day2_result = RepositoryAnalyzer(repository_path).analyze()
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    intelligence = run_and_store_code_intelligence(repository_path, day2_result)

    functions_found = sum(1 for symbol in intelligence.symbols if symbol.kind == "function")
    classes_found = sum(1 for symbol in intelligence.symbols if symbol.kind == "class")

    return CodeAnalysisSummaryResponse(
        status="success",
        files_parsed=intelligence.stats.files_parsed,
        files_skipped=intelligence.stats.files_skipped,
        parse_errors=intelligence.stats.parse_errors,
        functions_found=functions_found,
        classes_found=classes_found,
        imports_found=len(intelligence.imports),
        relationships_found=len(intelligence.relationships),
        routes_found=len(intelligence.routes),
    )


@router.get("/code-intelligence", response_model=CodeIntelligenceResponse)
def get_code_intelligence() -> CodeIntelligenceResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    data = analysis_storage.load(repository_path.name)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="No code intelligence analysis found. Run POST /repository/analyze-code first.",
        )
    return CodeIntelligenceResponse(**data)


@router.get("/graph", response_model=GraphResponse)
def get_repository_graph(focus: str | None = None) -> GraphResponse:
    try:
        return build_repository_graph(focus=focus)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
