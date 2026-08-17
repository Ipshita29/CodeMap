from typing import Literal

from pydantic import BaseModel

RiskLevel = Literal["low", "medium", "high", "critical"]
Confidence = Literal["high", "medium", "low", "unknown"]
DependencyType = Literal["imports", "calls"]


class ImpactedFile(BaseModel):
    path: str
    depth: int
    via: list[DependencyType]
    discovered_via: str  # the file this dependent was reached through, for drawing the actual chain


class RelatedRoute(BaseModel):
    method: str
    path: str
    file: str


class RelatedFile(BaseModel):
    path: str
    route: str
    confidence: Confidence


class RiskEstimate(BaseModel):
    level: RiskLevel
    score: int


class ImpactRequest(BaseModel):
    file: str


class ImpactResponse(BaseModel):
    file: str
    risk: RiskEstimate
    direct_dependents: list[ImpactedFile]
    indirect_dependents: list[ImpactedFile]
    related_routes: list[RelatedRoute]
    related_files: list[RelatedFile]
    truncated: bool
    summary: str | None = None
