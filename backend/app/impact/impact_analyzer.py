"""Change-impact analysis: reverse BFS over the same file-level relationship
index the architecture/dependency graph uses (imports + resolved calls,
collapsed to file granularity). No relationships are re-derived -- only
reachability is computed here.
"""

from __future__ import annotations

import posixpath
from collections import deque
from pathlib import Path

from app.graph.relationship_index import RelationshipIndex
from app.impact.api_call_matcher import extract_api_calls, match_route
from app.impact.impact_models import ImpactedFile, ImpactResponse, RelatedFile, RelatedRoute, RiskEstimate

MAX_DEPTH = 6
MAX_DEPENDENTS = 200
MAX_RELATED_FILE_SCAN = 300
ENTRY_POINT_BASENAMES = {"main", "index", "app", "server", "__init__"}


class ImpactAnalyzerError(Exception):
    pass


class ImpactAnalyzer:
    def __init__(self, repository_path: Path, intelligence: dict, index: RelationshipIndex):
        self.repository_path = repository_path
        self.intelligence = intelligence
        self.index = index
        self.routes = intelligence["routes"]

    def analyze(self, file: str) -> ImpactResponse:
        if file not in self.index.file_paths:
            raise ImpactAnalyzerError(f"'{file}' was not found in this repository's analyzed source files.")

        visited: dict[str, ImpactedFile] = {}
        seen = {file}
        queue = deque([(file, 0)])
        truncated = False

        while queue:
            current, depth = queue.popleft()
            if depth >= MAX_DEPTH:
                continue
            for edge in self.index.reverse(current):
                if edge.source in seen:
                    existing = visited.get(edge.source)
                    if existing and edge.type not in existing.via:
                        existing.via.append(edge.type)
                    continue
                if len(seen) >= MAX_DEPENDENTS:
                    truncated = True
                    continue
                seen.add(edge.source)
                entry = ImpactedFile(path=edge.source, depth=depth + 1, via=[edge.type], discovered_via=current)
                visited[edge.source] = entry
                queue.append((edge.source, depth + 1))

        direct = sorted((f for f in visited.values() if f.depth == 1), key=lambda f: f.path)
        indirect = sorted((f for f in visited.values() if f.depth > 1), key=lambda f: f.path)
        impacted_paths = seen  # includes `file` itself

        related_routes = [
            RelatedRoute(method=r["method"], path=r["path"], file=r["file"])
            for r in self.routes
            if r["file"] in impacted_paths
        ]
        related_files = self._find_related_frontend_callers(related_routes, exclude=impacted_paths)

        risk = self._score_risk(file, direct, indirect, related_routes)

        return ImpactResponse(
            file=file,
            risk=risk,
            direct_dependents=direct,
            indirect_dependents=indirect,
            related_routes=related_routes,
            related_files=related_files,
            truncated=truncated,
        )

    def _find_related_frontend_callers(self, related_routes: list[RelatedRoute], exclude: set[str]) -> list[RelatedFile]:
        """Files that call one of the impacted routes over HTTP -- a route-level
        connection, not a static import/call edge, so it's reported separately
        from direct/indirect dependents rather than folded into them."""
        if not related_routes:
            return []

        route_dicts = [route.model_dump() for route in related_routes]
        related: list[RelatedFile] = []
        candidates = [p for p in self.index.file_paths if p not in exclude][:MAX_RELATED_FILE_SCAN]

        for path in candidates:
            extension = posixpath.splitext(path)[1]
            try:
                content = (self.repository_path / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for call in extract_api_calls(content, extension):
                route, confidence = match_route(call.method, call.path, route_dicts)
                if route:
                    related.append(RelatedFile(path=path, route=f"{route['method']} {route['path']}", confidence=confidence))
                    break

        return related

    def _score_risk(
        self, file: str, direct: list[ImpactedFile], indirect: list[ImpactedFile], related_routes: list[RelatedRoute]
    ) -> RiskEstimate:
        symbol_count = sum(1 for s in self.intelligence["symbols"] if s["file"] == file)
        is_entry_point = posixpath.splitext(posixpath.basename(file))[0].lower() in ENTRY_POINT_BASENAMES

        score = (
            len(direct) * 8
            + len(indirect) * 3
            + len(related_routes) * 10
            + (15 if is_entry_point else 0)
            + min(symbol_count, 10)
        )
        score = min(score, 100)

        if score >= 80:
            level = "critical"
        elif score >= 55:
            level = "high"
        elif score >= 25:
            level = "medium"
        else:
            level = "low"

        return RiskEstimate(level=level, score=score)
