"""Reads Git metadata from an already-cloned repository -- commit history,
per-file history, and repository-wide activity statistics.

Read-only: never writes, commits, or mutates the repository's Git state.
Every statistic is bounded (MAX_HISTORY_LIMIT, MAX_ACTIVITY_COMMITS) so a
repository with tens of thousands of commits doesn't turn a page load into
a multi-minute walk -- see MAX_ACTIVITY_COMMITS for why: GitPython computes
real diff stats per commit for `commit.stats`, which is the expensive part.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import InvalidGitRepositoryError, NoSuchPathError, Repo
from git.exc import GitCommandError

from app.git.git_models import CommitEntry, FileCommitEntry, GitActivityResponse, HotspotEntry, LatestCommit

MAX_HISTORY_LIMIT = 200
MAX_FILE_HISTORY_LIMIT = 30
MAX_ACTIVITY_COMMITS = 300
MAX_HOTSPOTS = 10
# Repository-level contributors need the FULL commit history, not the
# recent-activity window above -- but only author identity, never
# `commit.stats` (the expensive per-commit diff computation MAX_ACTIVITY_
# COMMITS exists to bound), so this can afford to look much further back.
# Still capped, as a safety valve for pathologically huge histories rather
# than a limit real repositories are expected to hit.
MAX_CONTRIBUTOR_SCAN_COMMITS = 20_000


def _first_line(message: str) -> str:
    stripped = message.strip()
    return stripped.splitlines()[0] if stripped else "(no commit message)"


def _iso(commit) -> str:
    return commit.committed_datetime.astimezone(timezone.utc).isoformat()


class GitAnalyzer:
    def __init__(self, repository_path: Path):
        self.repository_path = repository_path
        self.repo: Repo | None = None
        self.available = False
        try:
            repo = Repo(repository_path)
            repo.head.commit  # touches an unborn HEAD (empty repo) to fail fast, deliberately
            self.repo = repo
            self.available = True
        except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
            self.available = False

    def latest_commit(self) -> LatestCommit | None:
        if not self.available:
            return None
        commit = self.repo.head.commit
        return LatestCommit(
            hash=commit.hexsha,
            short_hash=commit.hexsha[:7],
            message=_first_line(commit.message),
            author=commit.author.name or "unknown",
            date=_iso(commit),
        )

    def history(self, limit: int) -> tuple[list[CommitEntry], bool]:
        if not self.available:
            return [], False
        limit = max(1, min(limit, MAX_HISTORY_LIMIT))
        commits = list(self.repo.iter_commits(max_count=limit + 1))
        truncated = len(commits) > limit
        return [self._to_commit_entry(c) for c in commits[:limit]], truncated

    def file_history(self, file_path: str) -> tuple[list[FileCommitEntry], bool]:
        if not self.available:
            return [], False
        try:
            commits = list(self.repo.iter_commits(paths=file_path, max_count=MAX_FILE_HISTORY_LIMIT + 1))
        except GitCommandError:
            return [], False
        truncated = len(commits) > MAX_FILE_HISTORY_LIMIT
        entries = [
            FileCommitEntry(short_hash=c.hexsha[:7], message=_first_line(c.message), date=_iso(c))
            for c in commits[:MAX_FILE_HISTORY_LIMIT]
        ]
        return entries, truncated

    def repository_contributors(self) -> tuple[int, bool]:
        """Unique commit authors across the FULL commit history -- this is
        what "contributors" means as a repository-level fact (distinct from
        `activity().contributors`, which is deliberately scoped to the last
        MAX_ACTIVITY_COMMITS commits for its diff-stats work and represents
        recent-activity authors, not the repository's all-time contributor
        count). Author identity keys on email first since name alone
        collides more often (shared display names, renamed accounts).

        Returns (count, truncated) -- truncated is only ever true for
        histories longer than MAX_CONTRIBUTOR_SCAN_COMMITS.
        """
        if not self.available:
            return 0, False

        authors: set[str] = set()
        analyzed = 0
        truncated = False
        for commit in self.repo.iter_commits(max_count=MAX_CONTRIBUTOR_SCAN_COMMITS + 1):
            if analyzed >= MAX_CONTRIBUTOR_SCAN_COMMITS:
                truncated = True
                break
            analyzed += 1
            authors.add(commit.author.email or commit.author.name or "unknown")
        return len(authors), truncated

    def activity(self) -> GitActivityResponse:
        if not self.available:
            return GitActivityResponse(
                total_commits=0,
                contributors=0,
                commits_last_7_days=0,
                commits_last_30_days=0,
                most_modified_files=[],
                analyzed_commit_count=0,
                truncated=False,
            )

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        authors: set[str] = set()
        commits_7d = 0
        commits_30d = 0
        file_counts: dict[str, int] = {}
        analyzed = 0
        truncated = False

        for commit in self.repo.iter_commits(max_count=MAX_ACTIVITY_COMMITS + 1):
            if analyzed >= MAX_ACTIVITY_COMMITS:
                truncated = True
                break
            analyzed += 1
            authors.add(commit.author.email or commit.author.name or "unknown")
            committed_at = commit.committed_datetime.astimezone(timezone.utc)
            if committed_at >= seven_days_ago:
                commits_7d += 1
            if committed_at >= thirty_days_ago:
                commits_30d += 1
            try:
                for filename in commit.stats.files:
                    file_counts[filename] = file_counts.get(filename, 0) + 1
            except (GitCommandError, ValueError):
                continue

        hotspots = sorted(file_counts.items(), key=lambda item: item[1], reverse=True)[:MAX_HOTSPOTS]

        return GitActivityResponse(
            total_commits=analyzed,
            contributors=len(authors),
            commits_last_7_days=commits_7d,
            commits_last_30_days=commits_30d,
            most_modified_files=[HotspotEntry(path=path, commit_count=count) for path, count in hotspots],
            analyzed_commit_count=analyzed,
            truncated=truncated,
        )

    def _to_commit_entry(self, commit) -> CommitEntry:
        try:
            files_changed = len(commit.stats.files)
        except (GitCommandError, ValueError):
            files_changed = 0
        return CommitEntry(
            hash=commit.hexsha,
            short_hash=commit.hexsha[:7],
            message=_first_line(commit.message),
            author=commit.author.name or "unknown",
            date=_iso(commit),
            files_changed=files_changed,
        )
