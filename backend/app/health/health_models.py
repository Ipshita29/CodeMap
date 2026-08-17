from typing import Literal

from pydantic import BaseModel

Severity = Literal["low", "medium", "high"]
HealthCategoryName = Literal["structure", "dependencies", "complexity", "architecture", "documentation", "testing"]


class HealthFinding(BaseModel):
    severity: Severity
    category: HealthCategoryName
    path: str | None = None
    reason: str
    recommendation: str


class HealthCategories(BaseModel):
    structure: int
    dependencies: int
    complexity: int
    architecture: int
    documentation: int
    testing: int


class HealthResponse(BaseModel):
    score: int
    categories: HealthCategories
    findings: list[HealthFinding]
