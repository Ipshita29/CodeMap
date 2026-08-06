import re

from app.utils.exceptions import InvalidGitHubURLError

# Only allow https://github.com/<owner>/<repo>[.git] — this both rejects
# malformed input and closes off alternate git URL schemes (e.g. `ext::`,
# `file://`, embedded flags) that could otherwise be abused via GitPython.
GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\.git)?/?$"
)


def validate_github_url(url: str) -> str:
    """Validate a GitHub repository URL and return its repository name.

    Raises InvalidGitHubURLError if the URL is not a well-formed,
    clonable GitHub repository URL.
    """
    match = GITHUB_URL_PATTERN.match(url.strip())
    if not match:
        raise InvalidGitHubURLError(f"'{url}' is not a valid GitHub repository URL.")

    repo_name = match.group("repo")
    if repo_name in {".", ".."}:
        raise InvalidGitHubURLError(f"'{url}' is not a valid GitHub repository URL.")

    return repo_name
