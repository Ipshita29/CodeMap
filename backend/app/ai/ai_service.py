import logging

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.config.settings import settings
from app.utils.exceptions import AIRequestTimeoutError, AIServiceError, AIServiceNotConfiguredError

logger = logging.getLogger(__name__)


class AIService:
    """Thin wrapper around the OpenAI SDK.

    Nothing about prompt content or context assembly lives here — this is
    purely "send these messages, get text back, translate provider errors
    into our own exception types." Keeping OpenAI calls out of the API
    routes means the routes stay testable without a live API key.

    `openai_base_url` lets this point at any OpenAI-compatible provider
    (Groq, Gemini, OpenRouter, a local Ollama server, ...) instead of
    OpenAI itself -- the SDK and this class don't change, only config does.
    """

    def __init__(self):
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if not settings.openai_api_key:
            raise AIServiceNotConfiguredError(
                "No AI API key is configured. Set OPENAI_API_KEY in the backend environment."
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
                timeout=settings.openai_timeout_seconds,
            )
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        client = self._get_client()

        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
        except RateLimitError as exc:
            logger.warning("AI provider rate limit/quota error: %s", exc)
            raise AIServiceError(
                "The AI provider rejected the request (rate limit or quota exceeded). "
                "Please check your API key's usage limits and try again."
            ) from exc
        except APITimeoutError as exc:
            raise AIRequestTimeoutError("The AI request timed out. Please try again.") from exc
        except APIError as exc:
            logger.warning("AI provider API error: %s", exc)
            raise AIServiceError("The AI service returned an error. Please try again.") from exc

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            raise AIServiceError("The AI service returned an empty response.")
        return content.strip()


ai_service = AIService()
