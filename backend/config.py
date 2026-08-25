"""Application configuration -- environment variables, paths, and settings.
Loaded once as a module-level singleton (`settings`) so every other module
reads the same values instead of re-parsing the environment."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables."""

    app_name: str = "CodeMap API"
    cloned_repos_dir: Path = BACKEND_ROOT / "cloned_repos"
    analysis_output_dir: Path = BACKEND_ROOT / "analysis"
    cors_origins: list[str] = ["http://localhost:5173"]
    max_parseable_file_size_bytes: int = 500_000
    graph_max_file_nodes: int = 150

    # Root logger level -- see main.py, which is where this actually gets
    # applied via logging.basicConfig(). Any standard Python level name
    # ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") is valid; an unknown
    # value falls back to INFO rather than failing startup.
    log_level: str = "INFO"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 45.0
    # Any OpenAI-compatible provider works (Groq, Gemini, OpenRouter, a
    # local Ollama server, ...) -- set this to point the same `openai` SDK
    # client at a different endpoint. Leave unset to use OpenAI directly.
    openai_base_url: str | None = None

    ai_max_context_chars: int = 12_000
    ai_max_chars_per_file: int = 3_000
    ai_max_context_files: int = 8

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
