from fastapi import APIRouter, HTTPException

from app.graph.graph_service import build_repository_graph
from app.impact.impact_analyzer import ImpactAnalyzerError
from app.impact.impact_models import ImpactRequest, ImpactResponse
from app.impact.impact_service import analyze_change_impact
from app.models.analysis import AnalysisResponse, RepositoryTreeResponse
from app.models.code_intelligence import CodeAnalysisSummaryResponse, CodeIntelligenceResponse
from app.models.graph import GraphResponse
from app.models.repository import RepositoryImportRequest, RepositoryImportResponse
from app.services.analysis_storage import analysis_storage
from app.services.code_intelligence_service import run_and_store_code_intelligence
from app.services.git_service import git_service
from app.services.repository_snapshot import get_repository_snapshot
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
        result = get_repository_snapshot(repository_path)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AnalysisResponse(**result.to_dict())


@router.get("/tree", response_model=RepositoryTreeResponse)
def get_repository_tree() -> RepositoryTreeResponse:
    """The canonical file+folder tree -- the Architecture Repository Map
    renders this directly rather than reconstructing a tree from the
    (necessarily partial: parseable-files-only, node-capped) relationship
    graph. `total_files`/`total_folders` here are the exact same numbers
    Overview shows, since both come from the one cached snapshot."""
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = get_repository_snapshot(repository_path)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = result.to_dict()
    return RepositoryTreeResponse(
        tree=data["repository_tree"],
        total_files=data["total_files"],
        total_folders=data["total_folders"],
    )


@router.post("/analyze-code", response_model=CodeAnalysisSummaryResponse)
def analyze_code() -> CodeAnalysisSummaryResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        day2_result = get_repository_snapshot(repository_path)
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


@router.post("/impact", response_model=ImpactResponse)
def get_change_impact(payload: ImpactRequest) -> ImpactResponse:
    try:
        return analyze_change_impact(payload.file)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImpactAnalyzerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
