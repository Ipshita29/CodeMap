from pydantic import BaseModel, Field


class RepositoryImportRequest(BaseModel):
    github_url: str = Field(..., description="Public GitHub repository URL")


class RepositoryImportResponse(BaseModel):
    repository_name: str
    clone_path: str
    status: str
