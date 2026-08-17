from pydantic import BaseModel, Field


class PdfExportRequest(BaseModel):
    title: str
    markdown: str = Field(max_length=300_000)
