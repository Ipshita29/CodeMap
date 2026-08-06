import logging
import shutil
from pathlib import Path

from git import GitCommandError, Repo

from app.config.settings import settings
from app.utils.exceptions import RepositoryCloneError

logger = logging.getLogger(__name__)


class GitService:
    """Handles cloning GitHub repositories to local disk."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = (base_dir or settings.cloned_repos_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def clone_repository(self, github_url: str, repo_name: str) -> Path:
        """Clone a repository into base_dir/repo_name, replacing it if it already exists."""
        target_path = (self.base_dir / repo_name).resolve()

        # Defense in depth: repo_name is already validated upstream, but never
        # touch a path outside base_dir.
        if self.base_dir not in target_path.parents:
            raise RepositoryCloneError(f"Resolved clone path is unsafe: {target_path}")

        if target_path.exists():
            shutil.rmtree(target_path)

        try:
            Repo.clone_from(github_url, target_path)
        except GitCommandError as exc:
            shutil.rmtree(target_path, ignore_errors=True)
            # Log the full git output (may include local paths) server-side only;
            # the client gets a clean message with no filesystem details.
            logger.warning("git clone failed for %s: %s", github_url, exc)
            raise RepositoryCloneError(
                "Could not clone repository. Check that the URL is correct "
                "and the repository is public."
            ) from exc

        return target_path


git_service = GitService()
