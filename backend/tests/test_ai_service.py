import threading
import time

import pytest

import ai
from ai import AIService
from config import settings
from utils import AIServiceBusyError, AIServiceNotConfiguredError


def test_complete_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    service = AIService()
    with pytest.raises(AIServiceNotConfiguredError):
        service.complete("system prompt", "user prompt")


# =====================================================================
# AI concurrency protection -- AIService.complete() wraps the actual
# provider call in a threading.Semaphore (see its module docstring for why
# threading, not asyncio). These tests stub only client.chat.completions
# .create -- the real semaphore/acquire/release logic in complete() runs
# unmodified, unlike the ai_service.complete()-level stub other test files
# use for unrelated tests, which would bypass this entirely.
# =====================================================================


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def test_concurrent_completions_never_exceed_the_configured_limit(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake-key-for-this-test")

    active = 0
    max_active = 0
    lock = threading.Lock()

    class _FakeCompletions:
        def create(self, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.2)  # hold the slot briefly so concurrent calls genuinely overlap
            with lock:
                active -= 1
            return _FakeResponse("ok")

    class _FakeClient:
        class chat:
            completions = _FakeCompletions()

    service = AIService()
    monkeypatch.setattr(service, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(ai, "_ai_concurrency_semaphore", threading.Semaphore(2))

    threads = [threading.Thread(target=service.complete, args=("sys", "user")) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert max_active <= 2


def test_completion_beyond_the_limit_and_wait_window_raises_busy_error(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake-key-for-this-test")

    release_event = threading.Event()

    class _FakeCompletions:
        def create(self, **kwargs):
            release_event.wait(timeout=5)  # holds the only slot until the test releases it
            return _FakeResponse("ok")

    class _FakeClient:
        class chat:
            completions = _FakeCompletions()

    service = AIService()
    monkeypatch.setattr(service, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(ai, "_ai_concurrency_semaphore", threading.Semaphore(1))
    monkeypatch.setattr(ai, "_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", 0.3)

    holder_thread = threading.Thread(target=service.complete, args=("sys", "user"))
    holder_thread.start()
    time.sleep(0.1)  # let the holder actually acquire the only slot first

    try:
        with pytest.raises(AIServiceBusyError):
            service.complete("sys", "user")
    finally:
        release_event.set()
        holder_thread.join(timeout=5)
