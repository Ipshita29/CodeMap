from pathlib import Path

from app.analyzer.constants import IGNORED_DIRS

FolderTree = dict[str, "FolderTree"]


class FolderTreeBuilder:
    """Builds a nested folder-name tree, e.g. {"frontend": {"src": {...}}}.

    Ignored directory names are skipped *before* recursing into them, same
    pruning strategy as FileScanner. Kept separate from FileScanner (rather
    than derived from its output) so it stays a standalone, independently
    reusable module — the File Explorer feature can consume this without
    pulling in file-level scanning at all.
    """

    def __init__(self, root: Path):
        self.root = root
        self._folder_count = 0

    @property
    def folder_count(self) -> int:
        return self._folder_count

    def build(self) -> FolderTree:
        self._folder_count = 0
        return self._build_node(self.root)

    def _build_node(self, directory: Path) -> FolderTree:
        children: FolderTree = {}
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name.lower())
        except OSError:
            return children

        for entry in entries:
            if not entry.is_dir() or entry.name in IGNORED_DIRS:
                continue
            self._folder_count += 1
            children[entry.name] = self._build_node(entry)

        return children
