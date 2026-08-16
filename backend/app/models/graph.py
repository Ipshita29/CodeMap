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
    total_files: int
    message: str | None = None
