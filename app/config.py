"""
Configuration management.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv


def _load_environment() -> None:
    project_root_env = os.path.join(os.path.dirname(__file__), "../.env")
    if os.path.exists(project_root_env):
        load_dotenv(project_root_env, override=True)
        return

    load_dotenv(override=True)


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int, min_value: int = 1) -> int:
    """Parse an int env var, falling back (with a warning) on bad values.

    Raising at import time from the Config class body produces an opaque
    crash before validate() can run, so malformed values degrade to the
    default instead.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        import logging
        logging.getLogger("mirofish.config").warning(
            "Ignoring invalid %s=%r; using default %s", name, raw, default)
        return default
    return max(min_value, value)


def _resolve_path(default_path: str, env_name: str) -> str:
    raw_value = os.environ.get(env_name, default_path)
    return os.path.abspath(raw_value)


_load_environment()


class Config:
    """Application configuration."""

    DEBUG = _get_bool_env("DEBUG", False)

    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude-cli").strip().lower()

    # Post-simulation interviews for the final report. Each interviewed agent
    # costs one LLM call per platform, so the default stays small; raise it to
    # build a larger synthetic panel (>=6 also enables stratified sampling of
    # vocal / relevant / silent agents). EXTRA_QUESTIONS (';'-separated) are
    # appended to the generated questionnaire — useful for closed questions
    # whose answers can be coded into distributions.
    INTERVIEW_MAX_AGENTS = _get_int_env("MIROFISH_INTERVIEW_MAX_AGENTS", 5)
    INTERVIEW_EXTRA_QUESTIONS = os.environ.get("MIROFISH_INTERVIEW_EXTRA_QUESTIONS", "").strip()

    DATA_DIR = _resolve_path(os.path.join(os.path.dirname(__file__), "../data/graphs"), "DATA_DIR")

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), "../uploads"))
    ALLOWED_EXTENSIONS = {"pdf", "md", "txt", "markdown"}

    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get("OASIS_DEFAULT_MAX_ROUNDS", "10"))
    OASIS_SIMULATION_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../uploads/simulations"))

    OASIS_TWITTER_ACTIONS = [
        "CREATE_POST", "LIKE_POST", "REPOST", "FOLLOW", "DO_NOTHING", "QUOTE_POST",
    ]
    OASIS_REDDIT_ACTIONS = [
        "LIKE_POST", "DISLIKE_POST", "CREATE_POST", "CREATE_COMMENT",
        "LIKE_COMMENT", "DISLIKE_COMMENT", "SEARCH_POSTS", "SEARCH_USER",
        "TREND", "REFRESH", "DO_NOTHING", "FOLLOW", "MUTE",
    ]

    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get("REPORT_AGENT_MAX_TOOL_CALLS", "5"))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get("REPORT_AGENT_MAX_REFLECTION_ROUNDS", "2"))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get("REPORT_AGENT_TEMPERATURE", "0.5"))

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration."""
        errors: list[str] = []

        if cls.LLM_PROVIDER not in ("claude-cli", "codex-cli"):
            errors.append(f"LLM_PROVIDER must be 'claude-cli' or 'codex-cli', got '{cls.LLM_PROVIDER}'")

        return errors
