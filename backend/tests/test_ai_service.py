import pytest

from app.ai.ai_service import AIService
from app.config.settings import settings
from app.utils.exceptions import AIServiceNotConfiguredError


def test_complete_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    service = AIService()
    with pytest.raises(AIServiceNotConfiguredError):
        service.complete("system prompt", "user prompt")
