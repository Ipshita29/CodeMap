"""Shared file-level relationship index, built once from Day 3 code
intelligence and reused by the graph builder, the impact analyzer, and the
health analyzer.

This is the "one repository knowledge layer" those features all read from --
none of them re-derive relationships from raw Tree-sitter output
independently.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


def symbol_file(sid: str) -> str:
    return sid.split("::", 1)[0]


def external_package_name(source: str, language: str) -> str:
    if source.startswith("@"):
        parts = source.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else source
    if language == "Python":
        return source.split(".")[0]
    return source.split("/")[0]


@dataclass(frozen=True)
class FileEdge:
    source: str
    target: str
    type: str  # "imports" | "calls"


class RelationshipIndex:
    """Indexes Day 3 code intelligence into fast file-level lookups for
    graph/impact traversal."""

    def __init__(self, intelligence: dict):
        self.intelligence = intelligence
        self.files_by_path = {f["path"]: f for f in intelligence["files"]}
        self.file_paths = set(self.files_by_path.keys())

        self.file_edges: dict[tuple[str, str, str], int] = {}
        self.external_by_file: dict[tuple[str, str], dict] = {}
        self._forward: dict[str, list[FileEdge]] = defaultdict(list)
        self._reverse: dict[str, list[FileEdge]] = defaultdict(list)

        self._collect(intelligence)

    def _collect(self, intelligence: dict) -> None:
        for rel in intelligence["relationships"]:
            if rel["type"] == "imports":
                source, target = rel["source"], rel["target"]
                if target and source in self.file_paths and target in self.file_paths and source != target:
                    self._add_file_edge(source, target, "imports")
            elif rel["type"] == "calls":
                if not rel.get("resolved") or not rel.get("target"):
                    continue
                source_file = symbol_file(rel["source"])
                target_file = symbol_file(rel["target"])
                if source_file != target_file and source_file in self.file_paths and target_file in self.file_paths:
                    self._add_file_edge(source_file, target_file, "calls")

        for imp in intelligence["imports"]:
            if not imp["is_external"]:
                continue
            file = imp["file"]
            if file not in self.file_paths:
                continue
            language = self.files_by_path[file]["language"]
            package = external_package_name(imp["source"], language)
            key = (file, f"external:{package}")
            entry = self.external_by_file.setdefault(key, {"weight": 0, "label": package})
            entry["weight"] += 1

        for (source, target, edge_type) in self.file_edges:
            edge = FileEdge(source, target, edge_type)
            self._forward[source].append(edge)
            self._reverse[target].append(edge)

    def _add_file_edge(self, source: str, target: str, edge_type: str) -> None:
        key = (source, target, edge_type)
        self.file_edges[key] = self.file_edges.get(key, 0) + 1

    def forward(self, path: str) -> list[FileEdge]:
        return self._forward.get(path, [])

    def reverse(self, path: str) -> list[FileEdge]:
        """Files that depend on `path` (import it or call into it)."""
        return self._reverse.get(path, [])
