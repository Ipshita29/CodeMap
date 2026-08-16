from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.ai.ai_service import ai_service
from app.ai.context_builder import RepositoryContextBuilder
from app.ai.prompts import (
    BEGINNER_SUMMARY_PROMPT,
    CHAT_MODE_INSTRUCTIONS,
    DEVELOPER_SUMMARY_PROMPT,
    REPOSITORY_CHAT_PROMPT,
)
from app.analyzer.repository_analyzer import RepositoryAnalyzer
from app.models.ai import ChatRequest, ChatResponse, RepositorySummaryResponse
from app.services.code_intelligence_service import get_or_build_code_intelligence
from app.services.git_service import git_service
from app.utils.exceptions import (
    AIRequestTimeoutError,
    AIServiceError,
    AIServiceNotConfiguredError,
    NoRepositoryImportedError,
    RepositoryAnalysisError,
)

router = APIRouter(prefix="/repository", tags=["ai"])


def _get_context_builder(repository_path: Path) -> RepositoryContextBuilder:
    try:
        day2_result = RepositoryAnalyzer(repository_path).analyze()
    except RepositoryAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Builds Day 3 code intelligence on demand if /analyze-code hasn't been
    # run yet -- the AI features shouldn't require a separate manual step.
    intelligence = get_or_build_code_intelligence(repository_path, day2_result)
    return RepositoryContextBuilder(repository_path, day2_result, intelligence)


def _complete_or_raise(system_prompt: str, user_prompt: str) -> str:
    try:
        return ai_service.complete(system_prompt, user_prompt)
    except AIServiceNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIRequestTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/summary", response_model=RepositorySummaryResponse)
def generate_repository_summary() -> RepositorySummaryResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    builder = _get_context_builder(repository_path)
    # A summary has no specific question to key retrieval off of, so pull a
    # broad structural context instead of a narrow keyword-scored file set.
    context = builder.build_context("project overview architecture main features")

    beginner_summary = _complete_or_raise(BEGINNER_SUMMARY_PROMPT, context.system_context)
    developer_summary = _complete_or_raise(DEVELOPER_SUMMARY_PROMPT, context.system_context)

    return RepositorySummaryResponse(
        repository_name=builder.day2_result.repository_name,
        beginner_summary=beginner_summary,
        developer_summary=developer_summary,
        sources=context.sources,
    )


@router.post("/chat", response_model=ChatResponse)
def chat_with_repository(payload: ChatRequest) -> ChatResponse:
    try:
        repository_path = git_service.get_latest_cloned_repository()
    except NoRepositoryImportedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    builder = _get_context_builder(repository_path)
    context = builder.build_context(payload.question)

    system_prompt = f"{REPOSITORY_CHAT_PROMPT}\n\n{CHAT_MODE_INSTRUCTIONS[payload.mode]}"
    user_prompt = f"{context.system_context}\n\n## Question\n{payload.question}"
    answer = _complete_or_raise(system_prompt, user_prompt)

    return ChatResponse(answer=answer, sources=context.sources)
