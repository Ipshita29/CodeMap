from pydantic import BaseModel


class CommitEntry(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str
    files_changed: int


class LatestCommit(BaseModel):
    hash: str
    short_hash: str
    message: str
    author: str
    date: str


class GitHistoryResponse(BaseModel):
    commits: list[CommitEntry]
    truncated: bool
    has_git_history: bool


class FileCommitEntry(BaseModel):
    short_hash: str
    message: str
    date: str


class FileHistoryResponse(BaseModel):
    file: str
    commits: list[FileCommitEntry]
    truncated: bool
    has_git_history: bool


class HotspotEntry(BaseModel):
    path: str
    commit_count: int


class GitActivityResponse(BaseModel):
    total_commits: int
    contributors: int
    commits_last_7_days: int
    commits_last_30_days: int
    most_modified_files: list[HotspotEntry]
    analyzed_commit_count: int
    truncated: bool


class GitSummaryResponse(BaseModel):
    has_git_history: bool
    latest_commit: LatestCommit | None
    activity: GitActivityResponse
    timeline: list[CommitEntry]
    # Repository-wide unique commit authors (full history) -- the number
    # Overview shows as "contributors". Distinct from `activity.contributors`,
    # which is scoped to the recent analyzed-commit window and labeled as
    # such wherever it's shown (Git History).
    repository_contributors: int
    repository_contributors_truncated: bool
