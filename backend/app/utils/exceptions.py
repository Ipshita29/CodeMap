class InvalidGitHubURLError(Exception):
    """Raised when a provided string is not a valid, clonable GitHub repository URL."""


class RepositoryCloneError(Exception):
    """Raised when cloning a repository fails."""
