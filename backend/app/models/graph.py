from typing import Literal

from pydantic import BaseModel

NodeType = Literal["file", "folder", "external"]
EdgeType = Literal["imports", "calls"]


class GraphNodeData(BaseModel):
    label: str
    path: str | None = None
    language: str | None = None
    lines: int | None = None
    functions: int | None = None
    classes: int | None = None
    imports: int | None = None
    exports: int | None = None
    layer: str | None = None
    file_count: int | None = None
    parse_error: str | None = None


class GraphNode(BaseModel):
    id: str
    type: NodeType
    data: GraphNodeData


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: EdgeType
    weight: int = 1


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    mode: Literal["files", "folders"]
    truncated: bool
    # Files with a parseable relationship (imports/calls) that this
    # particular graph query is scoped to -- NOT the repository's total file
    # count. That's `AnalysisResponse.total_files` / `RepositoryTreeResponse
    # .total_files`, the canonical repository-wide number; this field only
    # describes the (necessarily partial) relationship graph itself.
    analyzed_file_count: int
    message: str | None = None
