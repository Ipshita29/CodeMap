import os
import time
from pathlib import Path

from app.ai import answer_cache


def _bump_mtime(path: Path) -> None:
    """Simulates GitService.clone_repository replacing the directory with a
    fresh clone -- the only thing answer_cache actually keys "repository
    version" on is the directory's own mtime."""
    new_time = time.time() + 5
    os.utime(path, (new_time, new_time))


def test_normalize_question_collapses_case_whitespace_and_punctuation():
    assert answer_cache.normalize_question("How does Login work?") == answer_cache.normalize_question(
        "  how does   login work  "
    )
    assert answer_cache.normalize_question("What is this?") == answer_cache.normalize_question("what is this")


def test_lookup_misses_until_stored(tmp_path):
    assert answer_cache.lookup(tmp_path, "developer", "How does login work?") is None

    answer_cache.store(tmp_path, "developer", "How does login work?", "Answer text.", ["auth.py"])

    hit = answer_cache.lookup(tmp_path, "developer", "How does login work?")
    assert hit is not None
    assert hit.answer == "Answer text."
    assert hit.sources == ["auth.py"]


def test_lookup_hits_on_normalized_variants(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Answer text.", [])

    hit = answer_cache.lookup(tmp_path, "developer", "  HOW DOES login WORK  ")
    assert hit is not None
    assert hit.answer == "Answer text."


def test_different_question_is_a_miss(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Answer text.", [])

    assert answer_cache.lookup(tmp_path, "developer", "How does logout work?") is None


def test_different_mode_is_a_separate_cache_entry(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Developer answer.", [])

    assert answer_cache.lookup(tmp_path, "beginner", "How does login work?") is None


def test_repository_version_change_invalidates_old_answers(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Old answer.", [])
    assert answer_cache.lookup(tmp_path, "developer", "How does login work?") is not None

    _bump_mtime(tmp_path)

    assert answer_cache.lookup(tmp_path, "developer", "How does login work?") is None


def test_history_is_newest_first_and_scoped_to_current_version(tmp_path):
    answer_cache.store(tmp_path, "developer", "First question?", "First answer.", [])
    answer_cache.store(tmp_path, "developer", "Second question?", "Second answer.", [])

    history = answer_cache.list_history(tmp_path)
    assert [entry.question for entry in history] == ["Second question?", "First question?"]

    _bump_mtime(tmp_path)
    assert answer_cache.list_history(tmp_path) == []


def test_repeated_store_does_not_duplicate_history_entry(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Answer.", [])
    answer_cache.store(tmp_path, "developer", "how does login work", "Answer.", [])

    history = answer_cache.list_history(tmp_path)
    assert len(history) == 1


def test_clear_history_empties_the_list_and_forces_a_fresh_cache_miss(tmp_path):
    answer_cache.store(tmp_path, "developer", "How does login work?", "Answer.", [])
    assert len(answer_cache.list_history(tmp_path)) == 1

    answer_cache.clear_history(tmp_path)

    assert answer_cache.list_history(tmp_path) == []
    assert answer_cache.lookup(tmp_path, "developer", "How does login work?") is None
