class InvalidGitHubURLError(Exception):
    """Raised when a provided string is not a valid, clonable GitHub repository URL."""


class RepositoryCloneError(Exception):
    """Raised when cloning a repository fails."""


class NoRepositoryImportedError(Exception):
    """Raised when analysis is requested but no repository has been imported yet."""


class RepositoryAnalysisError(Exception):
    """Raised when a cloned repository cannot be analyzed."""


class AIServiceError(Exception):
    """Base class for AI service failures."""


class AIServiceNotConfiguredError(AIServiceError):
    """Raised when no OpenAI API key is configured."""


class AIRequestTimeoutError(AIServiceError):
    """Raised when a request to the AI provider times out."""
