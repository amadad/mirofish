"""
Configuration management.
"""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_cors_origins() -> list[str]:
    value = os.environ.get("CORS_ORIGINS")
    if not value:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5001",
            "http://127.0.0.1:5001",
        ]
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _resolve_path(default_path: str, env_name: str) -> str:
    raw_value = os.environ.get(env_name, default_path)
    return os.path.abspath(raw_value)


# Load the .env file from project root.
project_root_env = os.path.join(os.path.dirname(__file__), "../../.env")

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    load_dotenv(override=True)


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_cors_origins():
    raw = os.environ.get('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    if raw.strip() == '*':
        return '*'
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


def _get_llm_api_key() -> str:
    explicit = os.environ.get('LLM_API_KEY', '')
    if explicit:
        return explicit

    provider = (os.environ.get('LLM_PROVIDER', '') or '').strip().lower()
    if provider == 'nexa':
        # Nexa local server does not require a real key, but OpenAI SDK needs a string
        return os.environ.get('NEXA_API_KEY', '') or 'nexa'
    if provider == 'anthropic':
        return os.environ.get('ANTHROPIC_API_KEY', '')

    return os.environ.get('OPENAI_API_KEY', '') or os.environ.get('ANTHROPIC_API_KEY', '')


def _get_env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, '') else default


class Config:
    """Flask configuration class."""

    # Flask config
    DEBUG = _get_bool_env("FLASK_DEBUG", False)
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    CORS_ORIGINS = _get_cors_origins()

    # JSON config
    JSON_AS_ASCII = False

    # LLM config
    LLM_API_KEY = _get_llm_api_key()
    LLM_BASE_URL = _get_env_or_default('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = _get_env_or_default('LLM_MODEL_NAME', 'gpt-4o-mini')
    # Providers: openai | anthropic | claude-cli | codex-cli | nexa (OpenAI-compatible local server)
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', '')

    # Graph storage config
    GRAPH_BACKEND = os.environ.get("GRAPH_BACKEND", "kuzu").lower()
    KUZU_DB_PATH = _resolve_path(os.path.join(os.path.dirname(__file__), "../data/kuzu_db"), "KUZU_DB_PATH")
    DATA_DIR = _resolve_path(os.path.join(os.path.dirname(__file__), "../data/json_graphs"), "DATA_DIR")
    GRAPH_DB_PATH = KUZU_DB_PATH

    # File upload config
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "../uploads"))
    ALLOWED_EXTENSIONS = {"pdf", "md", "txt", "markdown"}

    # Text processing config
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # OASIS simulation config
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get("OASIS_DEFAULT_MAX_ROUNDS", "10"))
    OASIS_SIMULATION_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../uploads/simulations"))

    # OASIS platform available actions
    OASIS_TWITTER_ACTIONS = [
        "CREATE_POST", "LIKE_POST", "REPOST", "FOLLOW", "DO_NOTHING", "QUOTE_POST"
    ]
    OASIS_REDDIT_ACTIONS = [
        "LIKE_POST", "DISLIKE_POST", "CREATE_POST", "CREATE_COMMENT",
        "LIKE_COMMENT", "DISLIKE_COMMENT", "SEARCH_POSTS", "SEARCH_USER",
        "TREND", "REFRESH", "DO_NOTHING", "FOLLOW", "MUTE",
    ]

    # Report agent config
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get("REPORT_AGENT_MAX_TOOL_CALLS", "5"))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get("REPORT_AGENT_MAX_REFLECTION_ROUNDS", "2"))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get("REPORT_AGENT_TEMPERATURE", "0.5"))

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        errors = []
        if cls.LLM_PROVIDER not in ("claude-cli", "codex-cli", "nexa") and not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not configured (set LLM_PROVIDER=claude-cli/codex-cli, or use nexa/local provider without a key)")
        if cls.GRAPH_BACKEND not in {"kuzu", "json"}:
            errors.append("GRAPH_BACKEND must be either 'kuzu' or 'json'")
        return errors
