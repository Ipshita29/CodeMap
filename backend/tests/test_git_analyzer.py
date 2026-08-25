from pathlib import Path

from git import Actor, Repo

from repository import GitAnalyzer


def _init_repo(repo_path: Path) -> Repo:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Default Author")
        cw.set_value("user", "email", "default@example.com")
    return repo


def _commit(repo: Repo, filename: str, content: str, message: str, author: Actor | None = None):
    (Path(repo.working_dir) / filename).write_text(content)
    repo.index.add([filename])
    return repo.index.commit(message, author=author) if author else repo.index.commit(message)


def test_repository_contributors_counts_unique_authors_across_full_history(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "a.py", "x = 1\n", "first commit", Actor("Author One", "one@example.com"))
    _commit(repo, "b.py", "y = 2\n", "second commit", Actor("Author Two", "two@example.com"))
    # Same author as the first commit -- must not be double-counted.
    _commit(repo, "c.py", "z = 3\n", "third commit", Actor("Author One", "one@example.com"))

    count, truncated = GitAnalyzer(tmp_path).repository_contributors()

    assert count == 2
    assert truncated is False


def test_repository_contributors_keys_on_email_not_display_name(tmp_path):
    # Two different people can share a display name; distinct emails must
    # still be counted as distinct contributors rather than collapsed.
    repo = _init_repo(tmp_path)
    _commit(repo, "a.py", "x = 1\n", "first commit", Actor("Alex", "alex1@example.com"))
    _commit(repo, "b.py", "y = 2\n", "second commit", Actor("Alex", "alex2@example.com"))

    count, _truncated = GitAnalyzer(tmp_path).repository_contributors()

    assert count == 2


def test_latest_commit_reports_the_current_head(tmp_path):
    repo = _init_repo(tmp_path)
    commit = _commit(repo, "a.py", "x = 1\n", "only commit")

    latest = GitAnalyzer(tmp_path).latest_commit()

    assert latest is not None
    assert latest.hash == commit.hexsha
    assert latest.short_hash == commit.hexsha[:7]


def test_history_returns_commits_newest_first(tmp_path):
    repo = _init_repo(tmp_path)
    first = _commit(repo, "a.py", "x = 1\n", "first commit")
    second = _commit(repo, "b.py", "y = 2\n", "second commit")

    entries, truncated = GitAnalyzer(tmp_path).history(limit=10)

    assert [e.hash for e in entries] == [second.hexsha, first.hexsha]
    assert truncated is False


def test_git_analyzer_is_unavailable_for_a_non_git_directory(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    analyzer = GitAnalyzer(tmp_path)

    assert analyzer.available is False
    assert analyzer.latest_commit() is None
    assert analyzer.repository_contributors() == (0, False)
