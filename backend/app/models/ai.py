from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChatMode = Literal["beginner", "developer"]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    mode: ChatMode = "beginner"

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be empty.")
        return stripped


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]


class RepositorySummaryResponse(BaseModel):
    repository_name: str
    beginner_summary: str
    developer_summary: str
    sources: list[str]
