"""Execution-flow tracing.

Never asks an LLM to guess the flow. Every step is either:
  - a resolved `calls` relationship from Day 3 (confidence: high)
  - a route registration directly parsed from code (confidence: high)
  - a route handler resolved via a verified import (confidence: high) or
    left as a named-but-unlocated symbol (confidence: unknown) -- never
    fabricated
  - a regex-detected frontend API call (confidence: medium, since it's a
    heuristic, not an AST-verified relationship) matched against a real
    route (confidence high/medium/unknown depending on match strength)

Traversal is bounded (MAX_DEPTH, MAX_NODES) and cycle-safe (visited symbol
ids), since call graphs can be circular and repositories can be huge.
"""

from __future__ import annotations

import posixpath
from itertools import count
from pathlib import Path

from app.flow.flow_models import FlowNode, FlowRelationship, FlowResponse
from app.flow.flow_resolver import extract_api_calls, match_route, resolve_handler_name, score_file_for_query
from app.graph.relationship_index import RelationshipIndex, symbol_file, symbol_name

MAX_DEPTH = 8
MAX_NODES = 40
MAX_API_CALLS_PER_SCOPE = 5
MAX_UNKNOWN_CALLS_PER_SYMBOL = 3


class FlowAnalyzerError(Exception):
    pass


class FlowAnalyzer:
    def __init__(self, repository_path: Path, intelligence: dict, index: RelationshipIndex):
        self.repository_path = repository_path
        self.intelligence = intelligence
        self.index = index
        self.routes = intelligence["routes"]
        self._source_cache: dict[str, str] = {}
        self._api_calls_cache: dict[str, list] = {}

    def resolve_start_file(self, query: str) -> str | None:
        scored = [
            (path, score_file_for_query(path, self.intelligence["symbols"], self.routes, query))
            for path in self.index.file_paths
        ]
        scored = [item for item in scored if item[1] > 0]
        if not scored:
            return None
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[0][0]

    def analyze(self, start_file: str, start_function: str | None = None) -> FlowResponse:
        if start_file not in self.index.file_paths:
            raise FlowAnalyzerError(f"'{start_file}' was not found in this repository's analyzed source files.")

        self._nodes: dict[str, FlowNode] = {}
        self._relationships: list[FlowRelationship] = []
        self._visited_symbols: set[str] = set()
        self._id_counter = count(1)
        self._truncated = False

        start_symbol = self.index.find_function(start_file, start_function) if start_function else None

        if start_symbol:
            sid = f"{start_file}::{start_function}"
            start_id = self._add_node("function", start_function, start_file)
            self._trace_from_symbol(sid, start_id, depth=0)
        else:
            start_id = self._add_node("file", posixpath.basename(start_file), start_file)
            self._trace_from_file(start_file, start_id, depth=0)

        message = None
        if len(self._relationships) == 0:
            message = (
                "No further execution steps could be confidently determined from this starting point. "
                "Try a more specific file or function -- e.g. a frontend file that calls an API, or a "
                "route handler."
            )
        elif self._truncated:
            message = f"Flow trace stopped after {MAX_NODES} nodes / depth {MAX_DEPTH} to avoid an unbounded trace."

        return FlowResponse(
            status="success",
            start=self._nodes[start_id],
            flow=list(self._nodes.values()),
            relationships=self._relationships,
            truncated=self._truncated,
            message=message,
        )

    # -- node bookkeeping ---------------------------------------------------

    def _add_node(self, node_type: str, name: str, path: str | None, method: str | None = None) -> str:
        nid = str(next(self._id_counter))
        self._nodes[nid] = FlowNode(id=nid, type=node_type, name=name, path=path, method=method)
        return nid

    def _budget_exhausted(self, depth: int) -> bool:
        return depth >= MAX_DEPTH or len(self._nodes) >= MAX_NODES

    # -- source / API-call helpers -------------------------------------------

    def _read_source(self, path: str) -> str:
        if path not in self._source_cache:
            try:
                self._source_cache[path] = (self.repository_path / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._source_cache[path] = ""
        return self._source_cache[path]

    def _api_calls_in_file(self, path: str):
        if path not in self._api_calls_cache:
            extension = Path(path).suffix
            self._api_calls_cache[path] = extract_api_calls(self._read_source(path), extension)
        return self._api_calls_cache[path]

    def _emit_api_calls(self, file: str, from_node_id: str, depth: int, line_range: tuple[int, int] | None) -> None:
        calls = self._api_calls_in_file(file)
        if line_range:
            calls = [c for c in calls if line_range[0] <= c.line <= line_range[1]]
        for call in calls[:MAX_API_CALLS_PER_SCOPE]:
            if self._budget_exhausted(depth):
                self._truncated = True
                return
            api_id = self._add_node("api", f"{call.method} {call.path}", None, method=call.method)
            self._relationships.append(
                FlowRelationship(
                    source=from_node_id,
                    target=api_id,
                    type="api_call",
                    confidence="medium",
                    reason=f"Detected `{call.method.lower()}` call to '{call.path}' in {file}:{call.line} (regex-based, not AST-verified).",
                )
            )
            route, confidence = match_route(call.method, call.path, self.routes)
            if route is None:
                continue
            self._follow_route(route, api_id, confidence, depth + 1)

    def _follow_route(self, route: dict, from_node_id: str, confidence: str, depth: int) -> None:
        handler_name = resolve_handler_name(route["handler"])
        symbol = self.index.find_function(route["file"], handler_name)
        source_file = None

        if symbol is None:
            source_file = self._resolve_via_import(route["file"], handler_name)
            if source_file:
                symbol = self.index.find_function(source_file, handler_name)

        reason = f"Matched route {route['method']} {route['path']} registered in {route['file']}:{route['line']}."
        if symbol:
            target_id = self._add_node("function", handler_name, symbol["file"])
            self._relationships.append(
                FlowRelationship(source=from_node_id, target=target_id, type="route", confidence=confidence, reason=reason)
            )
            self._trace_from_symbol(f"{symbol['file']}::{handler_name}", target_id, depth)
        else:
            target_id = self._add_node("function", handler_name, None)
            self._relationships.append(
                FlowRelationship(
                    source=from_node_id,
                    target=target_id,
                    type="route",
                    confidence="unknown",
                    reason=reason + " Handler implementation could not be located.",
                )
            )

    def _resolve_via_import(self, importing_file: str, name: str) -> str | None:
        for imp in self.intelligence["imports"]:
            if imp["file"] == importing_file and name in imp["imported_names"] and imp["resolved_target"]:
                return imp["resolved_target"]
        return None

    # -- traversal ------------------------------------------------------

    def _trace_from_file(self, file: str, node_id: str, depth: int) -> None:
        if self._budget_exhausted(depth):
            self._truncated = True
            return

        # A file that itself registers routes (e.g. authRoutes.js) --
        # each registration is directly extracted from code (high confidence).
        own_routes = [r for r in self.routes if r["file"] == file]
        for route in own_routes:
            if self._budget_exhausted(depth):
                self._truncated = True
                return
            api_id = self._add_node("api", f"{route['method']} {route['path']}", None, method=route["method"])
            self._relationships.append(
                FlowRelationship(
                    source=node_id,
                    target=api_id,
                    type="route",
                    confidence="high",
                    reason=f"Route registered directly in {file}:{route['line']}.",
                )
            )
            self._follow_route(route, api_id, "high", depth + 1)

        if own_routes:
            return

        # Otherwise, look for outgoing frontend API calls made anywhere in the file...
        self._emit_api_calls(file, node_id, depth, line_range=None)

        # ...and, since no specific function was requested, fall back to tracing
        # from the file's own top-level function(s) -- a named entry point
        # (main/run/handler/...) if one exists, else all of them (bounded).
        # This is an inferred starting point, not a verified one, so it's
        # marked medium confidence rather than presented as fact.
        own_functions = [
            s
            for s in self.intelligence["symbols"]
            if s["kind"] == "function" and s["file"] == file and not s["is_method"]
        ]
        for func in self._pick_entry_functions(own_functions):
            if self._budget_exhausted(depth):
                self._truncated = True
                return
            func_id = self._add_node("function", func["name"], file)
            self._relationships.append(
                FlowRelationship(
                    source=node_id,
                    target=func_id,
                    type="calls",
                    confidence="medium",
                    reason=(
                        f"No start function was specified, so tracing from `{func['name']}`, "
                        f"a function defined in {file}."
                    ),
                )
            )
            self._trace_from_symbol(f"{file}::{func['name']}", func_id, depth + 1)

    @staticmethod
    def _pick_entry_functions(functions: list[dict], limit: int = 3) -> list[dict]:
        entry_names = {"main", "run", "handler", "index", "start", "execute"}
        named = [f for f in functions if f["name"].lower() in entry_names]
        return named if named else functions[:limit]

    def _trace_from_symbol(self, sid: str, node_id: str, depth: int) -> None:
        if sid in self._visited_symbols or self._budget_exhausted(depth):
            if self._budget_exhausted(depth):
                self._truncated = True
            return
        self._visited_symbols.add(sid)

        symbol = self.index.symbol(sid)
        file = symbol_file(sid)

        if symbol:
            self._emit_api_calls(file, node_id, depth, line_range=(symbol["start_line"], symbol["end_line"]))

        emitted_unknown_names: set[str] = set()
        unknown_count = 0

        for rel in self.index.calls_from(sid):
            if self._budget_exhausted(depth):
                self._truncated = True
                return
            if rel.get("resolved") and rel.get("target"):
                target_sid = rel["target"]
                target_id = self._add_node("function", symbol_name(target_sid), symbol_file(target_sid))
                self._relationships.append(
                    FlowRelationship(
                        source=node_id,
                        target=target_id,
                        type="calls",
                        confidence="high",
                        reason="Directly detected function call, resolved to its definition.",
                    )
                )
                self._trace_from_symbol(target_sid, target_id, depth + 1)
            else:
                # Most unresolved calls here are stdlib/third-party calls (the
                # repo's own functions resolve above) -- deduped by name and
                # capped per symbol so a handful of library calls (df.drop,
                # logging.info, ...) don't drown out the real call chain.
                callee = rel.get("raw_callee") or "unknown call"
                if callee in emitted_unknown_names or unknown_count >= MAX_UNKNOWN_CALLS_PER_SYMBOL:
                    continue
                emitted_unknown_names.add(callee)
                unknown_count += 1
                target_id = self._add_node("function", callee, None)
                self._relationships.append(
                    FlowRelationship(
                        source=node_id,
                        target=target_id,
                        type="calls",
                        confidence="unknown",
                        reason="Call detected but its target could not be confidently resolved (likely a library/builtin call).",
                    )
                )
