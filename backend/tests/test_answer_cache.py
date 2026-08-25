import os
import time
from pathlib import Path

from git import Repo

import ai as answer_cache


def _bump_mtime(path: Path) -> None:
    """Simulates GitService.clone_repository replacing a non-Git directory
    with a fresh clone -- answer_cache falls back to mtime for repository
    version only when the directory isn't a Git repository at all."""
    new_time = time.time() + 5
    os.utime(path, (new_time, new_time))


def _init_repo_with_commit(repo_path: Path, filename: str = "a.py") -> str:
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (repo_path / filename).write_text("x = 1\n")
    repo.index.add([filename])
    return repo.index.commit("initial commit").hexsha


def _commit(repo_path: Path, filename: str, message: str) -> str:
    repo = Repo(repo_path)
    (repo_path / filename).write_text("y = 2\n")
    repo.index.add([filename])
    return repo.index.commit(message).hexsha


def test_normalize_question_collapses_case_whitespace_and_punctuation():
    assert answer_cache.normalize_question("How does Login work?") == answer_cache.normalize_question(
        "  how does   login work  "
    )
    assert answer_cache.normalize_question("What is this?") == answer_cache.normalize_question("what is this")


def test_lookup_misses_until_stored(tmp_path):
    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is None

    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer text.", ["auth.py"])

    hit = answer_cache.lookup_answer(tmp_path, "developer", "How does login work?")
    assert hit is not None
    assert hit.answer == "Answer text."
    assert hit.sources == ["auth.py"]


def test_lookup_hits_on_normalized_variants(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer text.", [])

    hit = answer_cache.lookup_answer(tmp_path, "developer", "  HOW DOES login WORK  ")
    assert hit is not None
    assert hit.answer == "Answer text."


def test_different_question_is_a_miss(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer text.", [])

    assert answer_cache.lookup_answer(tmp_path, "developer", "How does logout work?") is None


def test_different_mode_is_a_separate_cache_entry(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Developer answer.", [])

    assert answer_cache.lookup_answer(tmp_path, "beginner", "How does login work?") is None


def test_repository_version_change_invalidates_old_answers(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Old answer.", [])
    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is not None

    _bump_mtime(tmp_path)

    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is None


def test_history_is_newest_first_and_scoped_to_current_version(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "First question?", "First answer.", [])
    answer_cache.store_answer(tmp_path, "developer", "Second question?", "Second answer.", [])

    history = answer_cache.list_answer_history(tmp_path)
    assert [entry.question for entry in history] == ["Second question?", "First question?"]

    _bump_mtime(tmp_path)
    assert answer_cache.list_answer_history(tmp_path) == []


def test_repeated_store_does_not_duplicate_history_entry(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer.", [])
    answer_cache.store_answer(tmp_path, "developer", "how does login work", "Answer.", [])

    history = answer_cache.list_answer_history(tmp_path)
    assert len(history) == 1


def test_same_commit_reuses_the_cached_answer(tmp_path):
    _init_repo_with_commit(tmp_path)
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer text.", ["a.py"])

    # Re-checking against the exact same commit -- e.g. a second request in
    # the same session -- must still hit.
    hit = answer_cache.lookup_answer(tmp_path, "developer", "How does login work?")

    assert hit is not None
    assert hit.answer == "Answer text."


def test_different_commit_is_a_cache_miss(tmp_path):
    _init_repo_with_commit(tmp_path)
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Old answer.", [])
    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is not None

    _commit(tmp_path, "b.py", "second commit")

    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is None


def test_reimporting_the_same_repository_at_the_same_commit_keeps_the_cache(tmp_path):
    # Re-cloning without any new upstream commits (e.g. the user hits
    # "Import repository" again for the same repo/commit) must NOT be
    # treated as a version change and must not evict Ask CodeMap history --
    # only a real commit change should do that.
    _init_repo_with_commit(tmp_path)
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer.", [])

    # Directory mtime changes (as a re-clone's rmtree + fresh checkout
    # would), but the commit is identical.
    _bump_mtime(tmp_path)

    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is not None


def test_clear_history_empties_the_list_and_forces_a_fresh_cache_miss(tmp_path):
    answer_cache.store_answer(tmp_path, "developer", "How does login work?", "Answer.", [])
    assert len(answer_cache.list_answer_history(tmp_path)) == 1

    answer_cache.clear_answer_history(tmp_path)

    assert answer_cache.list_answer_history(tmp_path) == []
    assert answer_cache.lookup_answer(tmp_path, "developer", "How does login work?") is None
