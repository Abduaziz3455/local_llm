"""Environment-backed configuration.

Values come from the process environment. docker-compose passes the repo `.env`
via `env_file:`; for local runs `python-dotenv` loads `.env` if present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # optional — only needed when running outside Docker
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_admin_ids() -> frozenset[int]:
    """Parse the admin allow-list.

    Prefers ADMIN_USER_IDS (comma-separated) and falls back to the legacy
    single-value ADMIN_USER_ID so old `.env` files keep working.
    """
    raw = os.getenv("ADMIN_USER_IDS", "").strip() or os.getenv("ADMIN_USER_ID", "").strip()
    if not raw:
        raise RuntimeError(
            "Missing required environment variable: ADMIN_USER_IDS"
        )
    ids = {int(part.strip()) for part in raw.split(",") if part.strip()}
    if not ids:
        raise RuntimeError("ADMIN_USER_IDS contained no valid numeric ids")
    return frozenset(ids)


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_user_ids: frozenset[int]
    openwebui_url: str          # e.g. http://open-webui:8080  (no trailing slash, no /api)
    openwebui_api_key: str
    model_fast: str             # Open WebUI model-entry id used by default
    model_thinking: str         # Open WebUI model-entry id for /think
    db_path: str
    history_turns: int          # how many past user+assistant messages to replay in DMs
    request_timeout: float      # seconds — generous; a 9B can be slow
    response_timeout: float     # seconds — hard cap on one generation (anti-runaway)
    file_ttl_hours: float       # how long an uploaded doc stays attached for RAG
    max_stored_messages: int    # cap on stored messages per chat (older ones pruned)
    # --- tool calling (poll feature) ---
    llama_url: str              # llama-swap OpenAI endpoint, e.g. http://llama:8080/v1
    llama_api_key: str          # llama-swap --api-key (default "local")
    poll_model: str             # model id used for poll tool-calling decisions
    polls_enabled: bool         # master switch for the poll feature


def load_config() -> Config:
    return Config(
        bot_token=_require("TELEGRAM_BOT_TOKEN"),
        admin_user_ids=_load_admin_ids(),
        openwebui_url=os.getenv("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/"),
        openwebui_api_key=_require("OPENWEBUI_API_KEY"),
        model_fast=os.getenv("MODEL_FAST", "qwen-fast").strip(),
        model_thinking=os.getenv("MODEL_THINKING", "qwen-thinking").strip(),
        db_path=os.getenv("BOT_DB_PATH", "/data/bot.db"),
        history_turns=int(os.getenv("HISTORY_TURNS", "12")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "180")),
        response_timeout=float(os.getenv("RESPONSE_TIMEOUT", "120")),
        file_ttl_hours=float(os.getenv("FILE_TTL_HOURS", "24")),
        max_stored_messages=int(os.getenv("MAX_STORED_MESSAGES", "200")),
        llama_url=os.getenv("LLAMA_URL", "http://llama:8080/v1").rstrip("/"),
        llama_api_key=os.getenv("LLAMA_API_KEY", "local").strip(),
        poll_model=os.getenv("POLL_MODEL", "gemma-4-12b").strip(),
        polls_enabled=os.getenv("POLLS_ENABLED", "true").strip().lower()
        not in ("0", "false", "no", ""),
    )
