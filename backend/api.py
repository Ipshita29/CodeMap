"""api.py -- all HTTP routes.

Every route here does the same three things and nothing more: validate the
request, call the appropriate repository/analyzer/ai function, and
translate the result (or a domain exception) into an HTTP response. No
analysis logic lives in this file -- see repository.py, analyzer.py, and
ai.py for that.

Defines routers only -- no FastAPI app instance and no middleware. main.py
creates the app, registers these routers, and is the only place that
process/application startup happens.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

import ai
import analyzer
import repository
from utils import (
    AIRequestTimeoutError,
    AIServiceError,
    AIServiceNotConfiguredError,
    InvalidGitHubURLError,
    NoRepositoryImportedError,
    PdfExportRequest,
    RepositoryAnalysisError,
    RepositoryCloneError,
    render_markdown_to_pdf,
    validate_github_url,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Routers
# =====================================================================

health_router = APIRouter(tags=["health"])
repository_router = APIRouter(prefix="/repository", tags=["repository"])
ai_router = APIRouter(prefix="/repository", tags=["ai"])
git_router = APIRouter(prefix="/repository/git", tags=["git"])
health_analysis_router = APIRouter(prefix="/repository", tags=["health"])
export_router = APIRouter(prefix="/repository/export", tags=["export"])


# =====================================================================
# Health check
# =====================================================================


@health_router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


# =====================================================================
# Repository: import, canonical analysis, code intelligence, graph, impact
# =====================================================================


@repository_router.post("/import", response_model=repository.RepositoryImportResponse)
def import_repository(payload: repository.RepositoryImportRequest) -> repository.RepositoryImportResponse:
    try:
        repo_name = validate_github_url(payload.github_url)
    except InvalidGitHubURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        clone_path = repository.git_clone_service.clone_repository(payload.github_url, repo_name)
    except RepositoryCloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return repository.RepositoryImportResponse(
        repository_name=repo_name,
        clone_path=str(clone_path),
        status="success",
    )


@repository_router.get("/analyze", response_model=repository.AnalysisResponse)
def analyze_repository() -> repository.AnalysisResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = repository.get_repository_snapshot(repository_path)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return repository.AnalysisResponse(**result.to_dict())


@repository_router.get("/tree", response_model=repository.RepositoryTreeResponse)
def get_repository_tree() -> repository.RepositoryTreeResponse:
    """The canonical file+folder tree -- the Architecture Repository Map
    renders this directly rather than reconstructing a tree from the
    (necessarily partial: parseable-files-only, node-capped) relationship
    graph. total_files/total_folders here are the exact same numbers
    Overview shows, since both come from the one cached snapshot."""
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = repository.get_repository_snapshot(repository_path)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = result.to_dict()
    return repository.RepositoryTreeResponse(
        tree=data["repository_tree"],
        total_files=data["total_files"],
        total_folders=data["total_folders"],
    )


@repository_router.post("/analyze-code", response_model=analyzer.CodeAnalysisSummaryResponse)
def analyze_code() -> analyzer.CodeAnalysisSummaryResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        day2_result = repository.get_repository_snapshot(repository_path)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    intelligence = analyzer.run_and_store_code_intelligence(repository_path, day2_result)

    functions_found = sum(1 for symbol in intelligence.symbols if symbol.kind == "function")
    classes_found = sum(1 for symbol in intelligence.symbols if symbol.kind == "class")

    return analyzer.CodeAnalysisSummaryResponse(
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


@repository_router.get("/code-intelligence", response_model=analyzer.CodeIntelligenceResponse)
def get_code_intelligence() -> analyzer.CodeIntelligenceResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    data = analyzer.analysis_storage.load(repository_path.name)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="No code intelligence analysis found. Run POST /repository/analyze-code first.",
        )
    return analyzer.CodeIntelligenceResponse(**data)


@repository_router.get("/graph", response_model=analyzer.GraphResponse)
def get_repository_graph(focus: str | None = None) -> analyzer.GraphResponse:
    try:
        return analyzer.build_repository_graph(focus=focus)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@repository_router.post("/impact", response_model=analyzer.ImpactResponse)
def get_change_impact(payload: analyzer.ImpactRequest) -> analyzer.ImpactResponse:
    try:
        return analyzer.analyze_change_impact(payload.file)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except analyzer.ImpactAnalyzerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# =====================================================================
# AI: repository summary, Ask CodeMap chat + history
# =====================================================================


def _translate_ai_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, AIServiceNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, AIRequestTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _get_repository_intelligence(repository_path: Path) -> tuple[repository.AnalysisResult, dict]:
    """Obtains the canonical snapshot and code intelligence AI needs, so
    ai.py itself never has to reach into repository.py/analyzer.py. This is
    the orchestration step the AI layer used to do on its own (via a
    function-local `from analyzer import ...` to dodge a circular import);
    it belongs here instead -- api.py already depends on both modules, and
    ai.py's functions just take the results as parameters."""
    day2_result = repository.get_repository_snapshot(repository_path)
    # Builds Day 3 code intelligence on demand if /analyze-code hasn't been
    # run yet -- the AI features shouldn't require a separate manual step.
    intelligence = analyzer.get_or_build_code_intelligence(repository_path, day2_result)
    return day2_result, intelligence


@ai_router.post("/summary", response_model=ai.RepositorySummaryResponse)
def generate_repository_summary() -> ai.RepositorySummaryResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        day2_result, intelligence = _get_repository_intelligence(repository_path)
        return ai.generate_repository_summary(repository_path, day2_result, intelligence)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AIServiceError as exc:
        raise _translate_ai_errors(exc) from exc


@ai_router.post("/chat", response_model=ai.ChatResponse)
def chat_with_repository(payload: ai.ChatRequest) -> ai.ChatResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Cache check comes before any repository re-analysis or AI call -- a
    # hit costs nothing beyond a dict lookup and a Git HEAD read, so it
    # deliberately happens before _get_repository_intelligence.
    cached = ai.lookup_answer(repository_path, payload.mode, payload.question)
    if cached is not None:
        return ai.ChatResponse(**cached.__dict__, cached=True)

    try:
        day2_result, intelligence = _get_repository_intelligence(repository_path)
        return ai.answer_question(repository_path, payload.question, payload.mode, day2_result, intelligence)
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AIServiceError as exc:
        raise _translate_ai_errors(exc) from exc


@ai_router.get("/chat/history", response_model=ai.ChatHistoryResponse)
def get_chat_history() -> ai.ChatHistoryResponse:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ai.get_chat_history(repository_path)


@ai_router.delete("/chat/history", status_code=204)
def clear_chat_history() -> None:
    try:
        repository_path = repository.git_clone_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ai.clear_answer_history(repository_path)


# =====================================================================
# Git: summary, history, per-file history
# =====================================================================


@git_router.get("/summary", response_model=repository.GitSummaryResponse)
def git_summary() -> repository.GitSummaryResponse:
    try:
        return repository.get_git_summary()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@git_router.get("/history", response_model=repository.GitHistoryResponse)
def git_history(limit: int = 30) -> repository.GitHistoryResponse:
    try:
        return repository.get_commit_history(limit)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@git_router.get("/file-history", response_model=repository.FileHistoryResponse)
def git_file_history(path: str) -> repository.FileHistoryResponse:
    try:
        return repository.get_file_history(path)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# =====================================================================
# Repository health
# =====================================================================


@health_analysis_router.get("/health", response_model=analyzer.HealthResponse)
def get_repository_health() -> analyzer.HealthResponse:
    try:
        return analyzer.analyze_repository_health()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# =====================================================================
# Export
# =====================================================================


@export_router.post("/pdf")
def export_pdf(payload: PdfExportRequest) -> Response:
    """Pure rendering step: takes Markdown the client already assembled from
    data it already fetched, and turns it into a PDF. No repository access,
    no re-running analysis or AI -- this never re-derives anything."""
    try:
        pdf_bytes = render_markdown_to_pdf(payload.title, payload.markdown)
    except Exception as exc:  # noqa: BLE001 - a rendering quirk must never surface a raw traceback to the client
        logger.warning("PDF rendering failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not generate the PDF report. Please try again.") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="codemap-report.pdf"'},
    )
