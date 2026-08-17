from fastapi import APIRouter, HTTPException

from app.git.git_models import FileHistoryResponse, GitHistoryResponse, GitSummaryResponse
from app.git.git_service import get_commit_history, get_file_history, get_git_summary
from app.utils.exceptions import NoRepositoryImportedError

router = APIRouter(prefix="/repository/git", tags=["git"])


@router.get("/summary", response_model=GitSummaryResponse)
def git_summary() -> GitSummaryResponse:
    try:
        return get_git_summary()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/history", response_model=GitHistoryResponse)
def git_history(limit: int = 30) -> GitHistoryResponse:
    try:
        return get_commit_history(limit)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/file-history", response_model=FileHistoryResponse)
def git_file_history(path: str) -> FileHistoryResponse:
    try:
        return get_file_history(path)
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
