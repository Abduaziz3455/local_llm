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


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_user_id: int
    openwebui_url: str          # e.g. http://open-webui:8080  (no trailing slash, no /api)
    openwebui_api_key: str
    model_fast: str             # Open WebUI model-entry id used by default
    model_thinking: str         # Open WebUI model-entry id for /think
    db_path: str
    history_turns: int          # how many past user+assistant messages to replay in DMs
    request_timeout: float      # seconds — generous; a 9B can be slow


def load_config() -> Config:
    return Config(
        bot_token=_require("TELEGRAM_BOT_TOKEN"),
        admin_user_id=int(_require("ADMIN_USER_ID")),
        openwebui_url=os.getenv("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/"),
        openwebui_api_key=_require("OPENWEBUI_API_KEY"),
        model_fast=os.getenv("MODEL_FAST", "qwen-fast").strip(),
        model_thinking=os.getenv("MODEL_THINKING", "qwen-thinking").strip(),
        db_path=os.getenv("BOT_DB_PATH", "/data/bot.db"),
        history_turns=int(os.getenv("HISTORY_TURNS", "12")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "180")),
    )
