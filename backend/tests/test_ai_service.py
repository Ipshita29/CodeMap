import pytest

from ai import AIService
from config import settings
from utils import AIServiceNotConfiguredError


def test_complete_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    service = AIService()
    with pytest.raises(AIServiceNotConfiguredError):
        service.complete("system prompt", "user prompt")
