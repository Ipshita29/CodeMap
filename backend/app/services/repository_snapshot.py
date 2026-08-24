"""The one canonical repository snapshot -- every endpoint that needs Day 2
filesystem-derived facts (files, folders, languages, frameworks, line
counts, the repository tree) reads from here instead of independently
re-walking the repository filesystem.

Cached per repository path and keyed on the directory's own mtime: cloning
a repository always replaces its directory (see GitService.clone_repository,
which rmtree's then re-clones), so the mtime changes exactly when the
on-disk content actually changes -- no explicit invalidation call to
remember, and a stale snapshot is never served across a re-import.
"""

from __future__ import annotations

from pathlib import Path

from app.analyzer.repository_analyzer import AnalysisResult, RepositoryAnalyzer

_cache: dict[Path, tuple[float, AnalysisResult]] = {}


def get_repository_snapshot(repository_path: Path) -> AnalysisResult:
    repository_path = Path(repository_path)
    mtime = repository_path.stat().st_mtime

    cached = _cache.get(repository_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    result = RepositoryAnalyzer(repository_path).analyze()
    _cache[repository_path] = (mtime, result)
    return result
