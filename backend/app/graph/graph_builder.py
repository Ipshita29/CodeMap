"""Transforms Day 2/3 analysis output into a normalized node/edge graph for
React Flow.

Every edge traces back to a real `imports` or resolved `calls` relationship
the Day 3 analyzer found — nothing here invents structure. "contains" edges
(file -> the symbols it defines) are deliberately not emitted: this graph
only models file/folder/external nodes, and there's no symbol node for a
"contains" edge to point at yet (that's function-level graphing, out of
scope for Day 5).
"""

from __future__ import annotations

import posixpath

from app.graph.relationship_index import RelationshipIndex
from app.models.graph import GraphEdge, GraphNode, GraphNodeData, GraphResponse

FRONTEND_MARKERS = {"frontend", "client", "web"}
BACKEND_MARKERS = {"backend", "server", "api"}
ROOT_FOLDER_ID = "."
MAX_EXTERNAL_NODES = 30

FileEdgeKey = tuple[str, str, str]  # (source_path, target_path, edge_type)
ExternalEdgeKey = tuple[str, str]  # (file_path, external_node_id)


def _top_level_folder(path: str) -> str:
    return _folder_at_depth(path, 1)


def _folder_at_depth(path: str, depth: int) -> str:
    """Groups `path` by its first `depth` folder segments. A file that
    doesn't have `depth` segments of its own (e.g. a file sitting directly
    in the folder being grouped at this depth) is grouped under its
    immediate parent instead, same as `depth=1` already did for root-level
    files -- this just generalizes that to any depth."""
    parts = path.split("/")
    if len(parts) <= depth:
        return "/".join(parts[:-1]) or ROOT_FOLDER_ID
    return "/".join(parts[:depth])


class GraphBuilder:
    def __init__(self, day2_files: list[dict], intelligence: dict, max_file_nodes: int, index: RelationshipIndex | None = None):
        self.day2_files = day2_files
        self.intelligence = intelligence
        self.max_file_nodes = max_file_nodes
        self.index = index or RelationshipIndex(intelligence)

    def build(self, focus: str | None = None) -> GraphResponse:
        lines_by_path = {f["path"]: f["lines"] for f in self.day2_files}
        intel_files = self.index.files_by_path
        file_paths = list(intel_files.keys())
        total_files = len(file_paths)

        layer_by_path = self._guess_layers(file_paths)
        file_edges, external_by_file = self.index.file_edges, self.index.external_by_file

        if focus:
            focus = focus.strip("/")
            scoped = self._scope_to_focus(focus, file_paths, file_edges)

            if len(scoped) > self.max_file_nodes:
                # A single extra folder-depth level isn't always enough for a
                # monorepo (e.g. focusing "packages" can still contain hundreds
                # of files one level down) -- keep grouping one level deeper
                # until the node count is manageable, or we run out of
                # meaningful depth to add.
                depth = focus.count("/") + 2
                nodes, edges = self._build_folder_graph(scoped, file_edges, external_by_file, depth, root=focus)
                return GraphResponse(
                    nodes=nodes,
                    edges=edges,
                    mode="folders",
                    truncated=True,
                    total_files=total_files,
                    message=(
                        f"'{focus}' contains {len(scoped)} files. Showing its subfolders — "
                        "click one or use search to explore specific files."
                    ),
                )

            nodes = self._build_file_nodes(scoped, intel_files, lines_by_path, layer_by_path)
            nodes += self._build_external_nodes(external_by_file, scoped)
            edges = self._build_file_edges(file_edges, scoped)
            edges += self._build_external_edges(external_by_file, scoped)
            return GraphResponse(
                nodes=nodes,
                edges=edges,
                mode="files",
                truncated=len(scoped) < total_files,
                total_files=total_files,
                message=f"Showing {len(scoped)} files under '{focus}' and their direct connections.",
            )

        if total_files > self.max_file_nodes:
            nodes, edges = self._build_folder_graph(file_paths, file_edges, external_by_file, depth=1, root=ROOT_FOLDER_ID)
            return GraphResponse(
                nodes=nodes,
                edges=edges,
                mode="folders",
                truncated=True,
                total_files=total_files,
                message=(
                    f"This repository has {total_files} source files. Showing the top-level folder "
                    "structure first — click a folder or use search to explore specific files."
                ),
            )

        all_paths = set(file_paths)
        nodes = self._build_file_nodes(file_paths, intel_files, lines_by_path, layer_by_path)
        nodes += self._build_external_nodes(external_by_file, all_paths)
        edges = self._build_file_edges(file_edges, all_paths)
        edges += self._build_external_edges(external_by_file, all_paths)
        return GraphResponse(
            nodes=nodes, edges=edges, mode="files", truncated=False, total_files=total_files, message=None
        )

    # -- layer heuristics -----------------------------------------------

    def _guess_layers(self, file_paths: list[str]) -> dict[str, str]:
        """Tags files as frontend/backend only when the repo's own top-level
        folder names make that unambiguous. Otherwise leaves layers unset
        rather than inventing an architecture that isn't there."""
        top_dirs = {_top_level_folder(p) for p in file_paths}
        if not (top_dirs & FRONTEND_MARKERS and top_dirs & BACKEND_MARKERS):
            return {}

        layers: dict[str, str] = {}
        for path in file_paths:
            top = _top_level_folder(path)
            if top in FRONTEND_MARKERS:
                layers[path] = "frontend"
            elif top in BACKEND_MARKERS:
                layers[path] = "backend"
        return layers

    # -- scoping / aggregation -------------------------------------------

    def _scope_to_focus(self, focus: str, file_paths: list[str], file_edges: dict[FileEdgeKey, int]) -> set[str]:
        focus = focus.strip("/")
        direct = {p for p in file_paths if p == focus or p.startswith(f"{focus}/")}
        neighbors: set[str] = set()
        for source, target, _ in file_edges:
            if source in direct:
                neighbors.add(target)
            if target in direct:
                neighbors.add(source)
        return direct | neighbors

    def _build_folder_graph(
        self,
        file_paths: list[str],
        file_edges: dict[FileEdgeKey, int],
        external_by_file: dict[ExternalEdgeKey, dict],
        depth: int,
        root: str,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        folder_of = {p: _folder_at_depth(p, depth) for p in file_paths}
        folder_counts: dict[str, int] = {}
        for folder in folder_of.values():
            folder_counts[folder] = folder_counts.get(folder, 0) + 1

        def _label(folder: str) -> str:
            if folder == root:
                return "(root)" if root == ROOT_FOLDER_ID else f"{root} (direct files)"
            return folder

        nodes = [
            GraphNode(
                id=folder,
                type="folder",
                data=GraphNodeData(label=_label(folder), path=folder, file_count=count),
            )
            for folder, count in sorted(folder_counts.items())
        ]

        folder_edges: dict[FileEdgeKey, int] = {}
        for (source, target, edge_type), weight in file_edges.items():
            # `file_paths` (and so `folder_of`) may be a scoped subset of the
            # repo rather than every file -- skip edges that reach outside it.
            if source not in folder_of or target not in folder_of:
                continue
            source_folder, target_folder = folder_of[source], folder_of[target]
            if source_folder == target_folder:
                continue
            key = (source_folder, target_folder, edge_type)
            folder_edges[key] = folder_edges.get(key, 0) + weight

        edges = [
            GraphEdge(id=f"{s}->{t}:{et}", source=s, target=t, type=et, weight=w)
            for (s, t, et), w in folder_edges.items()
        ]

        folder_external: dict[ExternalEdgeKey, dict] = {}
        total_weight_by_external: dict[str, int] = {}
        for (file, external_id), entry in external_by_file.items():
            if file not in folder_of:
                continue
            folder = folder_of[file]
            key = (folder, external_id)
            bucket = folder_external.setdefault(key, {"weight": 0, "label": entry["label"]})
            bucket["weight"] += entry["weight"]
            total_weight_by_external[external_id] = total_weight_by_external.get(external_id, 0) + entry["weight"]

        # An aggregated view is dominated by however many *folders* there
        # are, not files -- an uncapped external list (one node per package
        # ever imported, repo-wide) can dwarf that and bury the actual
        # repository structure. Keep only the packages most imported overall.
        kept_external_ids = {
            eid for eid, _ in sorted(total_weight_by_external.items(), key=lambda item: item[1], reverse=True)[:MAX_EXTERNAL_NODES]
        }

        seen_external: dict[str, str] = {}
        for (folder, external_id), entry in folder_external.items():
            if external_id not in kept_external_ids:
                continue
            edges.append(
                GraphEdge(id=f"{folder}->{external_id}", source=folder, target=external_id, type="imports", weight=entry["weight"])
            )
            seen_external.setdefault(external_id, entry["label"])

        nodes += [GraphNode(id=eid, type="external", data=GraphNodeData(label=label)) for eid, label in seen_external.items()]
        return nodes, edges

    # -- node/edge construction -------------------------------------------

    def _build_file_nodes(
        self,
        paths,
        intel_files: dict[str, dict],
        lines_by_path: dict[str, int],
        layer_by_path: dict[str, str],
    ) -> list[GraphNode]:
        nodes = []
        for path in paths:
            entry = intel_files[path]
            nodes.append(
                GraphNode(
                    id=path,
                    type="file",
                    data=GraphNodeData(
                        label=posixpath.basename(path),
                        path=path,
                        language=entry["language"],
                        lines=lines_by_path.get(path),
                        functions=entry.get("functions_count"),
                        classes=entry.get("classes_count"),
                        imports=entry.get("imports_count"),
                        exports=entry.get("exports_count"),
                        layer=layer_by_path.get(path),
                        parse_error=entry.get("parse_error"),
                    ),
                )
            )
        return nodes

    def _build_file_edges(self, file_edges: dict[FileEdgeKey, int], scoped_paths: set[str]) -> list[GraphEdge]:
        return [
            GraphEdge(id=f"{source}->{target}:{edge_type}", source=source, target=target, type=edge_type, weight=weight)
            for (source, target, edge_type), weight in file_edges.items()
            if source in scoped_paths and target in scoped_paths
        ]

    def _build_external_edges(
        self, external_by_file: dict[ExternalEdgeKey, dict], scoped_paths: set[str]
    ) -> list[GraphEdge]:
        return [
            GraphEdge(id=f"{file}->{external_id}", source=file, target=external_id, type="imports", weight=entry["weight"])
            for (file, external_id), entry in external_by_file.items()
            if file in scoped_paths
        ]

    def _build_external_nodes(
        self, external_by_file: dict[ExternalEdgeKey, dict], scoped_paths: set[str]
    ) -> list[GraphNode]:
        seen: dict[str, str] = {}
        for (file, external_id), entry in external_by_file.items():
            if file in scoped_paths and external_id not in seen:
                seen[external_id] = entry["label"]
        return [GraphNode(id=eid, type="external", data=GraphNodeData(label=label)) for eid, label in seen.items()]
