"""In-memory cache for Ask CodeMap answers.

Keyed on repository identity + repository *version* + mode + normalized
question, so re-asking the same question against an unchanged repository
never triggers a second AI call, but a repository re-import can never serve
a stale answer generated against the old code.

"Repository version" reuses the exact signal repository_snapshot.py already
uses to invalidate the Day 2 analysis: the clone directory's own mtime,
which only changes when GitService.clone_repository replaces it (rmtree +
a fresh clone). Reusing that signal here means both caches agree on what
counts as "the repository changed" without a second versioning scheme.

No persistence layer, same as the rest of this app's in-memory state
(repository_snapshot, the git clone location itself) -- lost on restart,
rebuilt on demand. A repository path keeps only its current version's
entries; asking a fresh version prunes the previous one instead of leaking
memory across repeated re-imports in a long-running process.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path


def normalize_question(question: str) -> str:
    """Collapses differences that shouldn't count as a different question --
    case, surrounding/internal whitespace, and trailing punctuation. E.g.
    "How does Login work?" and "how does login work" normalize the same."""
    collapsed = re.sub(r"\s+", " ", question.strip().lower())
    return collapsed.rstrip("?.! ")


@dataclass
class AnswerCacheEntry:
    id: str
    question: str  # original wording, for display
    mode: str
    answer: str
    sources: list[str] = field(default_factory=list)
    asked_at: float = 0.0


_cache: dict[str, AnswerCacheEntry] = {}
_history: dict[str, list[str]] = {}  # repo-version key -> cache keys, oldest first
_latest_version_by_path: dict[str, str] = {}  # repo path -> its current repo-version key


def _repository_version_key(repository_path: Path) -> str:
    repository_path = Path(repository_path)
    return f"{repository_path}@{repository_path.stat().st_mtime}"


def _cache_key(repo_version_key: str, mode: str, normalized_question: str) -> str:
    return f"{repo_version_key}::{mode}::{normalized_question}"


def _current_version(repository_path: Path) -> str:
    """Resolves the repository's current version key and prunes any cache
    entries left over from a previous version of the same path."""
    repository_path = Path(repository_path)
    repo_version_key = _repository_version_key(repository_path)

    path_str = str(repository_path)
    previous = _latest_version_by_path.get(path_str)
    if previous is not None and previous != repo_version_key:
        for stale_key in _history.pop(previous, []):
            _cache.pop(stale_key, None)
    _latest_version_by_path[path_str] = repo_version_key

    return repo_version_key


def lookup(repository_path: Path, mode: str, question: str) -> AnswerCacheEntry | None:
    repo_version_key = _current_version(repository_path)
    key = _cache_key(repo_version_key, mode, normalize_question(question))
    return _cache.get(key)


def store(repository_path: Path, mode: str, question: str, answer: str, sources: list[str]) -> AnswerCacheEntry:
    repo_version_key = _current_version(repository_path)
    key = _cache_key(repo_version_key, mode, normalize_question(question))

    entry = _cache.get(key)
    if entry is None:
        entry = AnswerCacheEntry(
            id=key, question=question.strip(), mode=mode, answer=answer, sources=sources, asked_at=time.time()
        )
        _cache[key] = entry
        _history.setdefault(repo_version_key, []).append(key)
    else:
        # A second generation for the same key shouldn't normally happen --
        # lookup() would have short-circuited first -- but stay authoritative
        # rather than leave a mismatched entry if it does (e.g. a race
        # between two concurrent requests for a brand-new question).
        entry.answer = answer
        entry.sources = sources
    return entry


def list_history(repository_path: Path) -> list[AnswerCacheEntry]:
    """Newest first, scoped to the repository's current version only -- an
    older version's questions are never listed, so a stale answer can never
    be selected from history after the repository changes."""
    repo_version_key = _current_version(repository_path)
    keys = _history.get(repo_version_key, [])
    return [_cache[key] for key in reversed(keys) if key in _cache]


def clear_history(repository_path: Path) -> None:
    """Drops every cached answer for the repository's current version --
    an explicit user action (the history popover's "Clear history"), not
    something the cache does on its own. Re-asking a question afterward is
    a normal cache miss, same as if it had never been asked."""
    repo_version_key = _current_version(repository_path)
    for key in _history.pop(repo_version_key, []):
        _cache.pop(key, None)
