from typing import Literal

from pydantic import BaseModel

Confidence = Literal["high", "medium", "low", "unknown"]
FlowNodeType = Literal["file", "function", "api"]


class FlowNode(BaseModel):
    id: str
    type: FlowNodeType
    name: str
    path: str | None = None
    method: str | None = None  # set when type == "api"


class FlowRelationship(BaseModel):
    source: str
    target: str
    type: Literal["calls", "api_call", "route"]
    confidence: Confidence
    reason: str


class FlowRequest(BaseModel):
    start_file: str | None = None
    start_function: str | None = None
    query: str | None = None


class FlowResponse(BaseModel):
    status: Literal["success"]
    start: FlowNode
    flow: list[FlowNode]
    relationships: list[FlowRelationship]
    truncated: bool
    message: str | None = None
