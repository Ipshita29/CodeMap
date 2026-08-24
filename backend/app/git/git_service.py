from app.git.git_analyzer import GitAnalyzer
from app.git.git_models import FileHistoryResponse, GitHistoryResponse, GitSummaryResponse
from app.services.git_service import git_service as clone_locator


def _analyzer() -> GitAnalyzer:
    repository_path = clone_locator.get_latest_cloned_repository()
    return GitAnalyzer(repository_path)


def get_commit_history(limit: int) -> GitHistoryResponse:
    analyzer = _analyzer()
    commits, truncated = analyzer.history(limit)
    return GitHistoryResponse(commits=commits, truncated=truncated, has_git_history=analyzer.available)


def get_file_history(file_path: str) -> FileHistoryResponse:
    analyzer = _analyzer()
    commits, truncated = analyzer.file_history(file_path)
    return FileHistoryResponse(
        file=file_path, commits=commits, truncated=truncated, has_git_history=analyzer.available
    )


def get_git_summary() -> GitSummaryResponse:
    analyzer = _analyzer()
    timeline, _ = analyzer.history(15)
    repository_contributors, contributors_truncated = analyzer.repository_contributors()
    return GitSummaryResponse(
        has_git_history=analyzer.available,
        latest_commit=analyzer.latest_commit(),
        activity=analyzer.activity(),
        timeline=timeline,
        repository_contributors=repository_contributors,
        repository_contributors_truncated=contributors_truncated,
    )
