"""Builds the one canonical file+folder tree every tree-based UI (the
Architecture Repository Map, the AI context's folder summary, ...) reads
from.

Deliberately built from the *file paths FileScanner already discovered*
rather than a second `os.walk`/`iterdir` pass over disk: every file that
contributes to `total_files`/`languages`/line counts also contributes its
directory chain here, which is what makes `total_folders` (the count of
directory nodes produced below) provably consistent with the tree instead
of two independently-computed numbers that can drift apart. A directory
that owns zero files can't exist in a git-cloned repository anyway (git
doesn't track empty directories), so this loses nothing real.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TreeNode:
    name: str
    type: str  # "file" | "directory"
    path: str
    children: list["TreeNode"] | None = field(default=None)

    def to_dict(self) -> dict:
        data: dict = {"name": self.name, "type": self.type, "path": self.path}
        if self.children is not None:
            data["children"] = [child.to_dict() for child in self.children]
        return data


def build_repository_tree(file_paths: list[str]) -> tuple[list[TreeNode], int]:
    """Returns (root-level nodes, directory_count).

    `directory_count` is every directory node in the tree, at any depth --
    the repository root itself is never counted (root isn't a folder
    *within* the repository, it IS the repository), matching the existing
    "total_folders excludes root" definition.
    """
    root: dict = {}

    for relative_path in file_paths:
        parts = relative_path.split("/")
        cursor = root
        for index, part in enumerate(parts):
            is_terminal = index == len(parts) - 1
            node_path = "/".join(parts[: index + 1])
            if part not in cursor:
                cursor[part] = {
                    "name": part,
                    "path": node_path,
                    "is_file": is_terminal,
                    "children": {},
                }
            entry = cursor[part]
            if is_terminal:
                # A real filesystem path can't be both a file and a directory,
                # so the terminal segment always wins as "file" -- this only
                # matters if scanned paths were ever malformed/duplicated.
                entry["is_file"] = True
            cursor = entry["children"]

    directory_count = 0

    def _finalize(level: dict) -> list[TreeNode]:
        nonlocal directory_count
        nodes: list[TreeNode] = []
        for entry in level.values():
            if entry["is_file"]:
                nodes.append(TreeNode(name=entry["name"], type="file", path=entry["path"]))
            else:
                directory_count += 1
                nodes.append(
                    TreeNode(
                        name=entry["name"],
                        type="directory",
                        path=entry["path"],
                        children=_finalize(entry["children"]),
                    )
                )
        nodes.sort(key=lambda node: (node.type != "directory", node.name.lower()))
        return nodes

    return _finalize(root), directory_count
