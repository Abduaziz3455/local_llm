"""Per-chat persistence: conversation history and chat settings.

Used only for DM chats — guest-mode interactions are stateless by design
(Telegram delivers no chat history for them).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import aiosqlite

Mode = Literal["fast", "thinking"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    chat_id INTEGER NOT NULL,
    role    TEXT    NOT NULL,          -- 'user' | 'assistant'
    content TEXT    NOT NULL,
    ts      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, ts);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id    INTEGER PRIMARY KEY,
    mode       TEXT    NOT NULL DEFAULT 'fast',
    web_search INTEGER NOT NULL DEFAULT 1   -- 1 = on, 0 = off
);

CREATE TABLE IF NOT EXISTS chat_files (
    chat_id  INTEGER NOT NULL,             -- DM chat the file is attached to
    file_id  TEXT    NOT NULL,             -- Open WebUI file id
    filename TEXT    NOT NULL,
    ts       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_files ON chat_files(chat_id, ts);
"""


@dataclass(frozen=True)
class ChatSettings:
    mode: Mode
    web_search: bool


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database.connect() was not awaited")
        return self._db

    # --- conversation history ------------------------------------------------

    async def add_message(self, chat_id: int, role: str, content: str) -> None:
        await self._conn.execute(
            "INSERT INTO messages (chat_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, time.time()),
        )
        await self._conn.commit()

    async def get_history(self, chat_id: int, limit: int) -> list[dict[str, str]]:
        """Return the last ``limit`` messages for a chat, oldest first."""
        async with self._conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? "
            "ORDER BY ts DESC LIMIT ?",
            (chat_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def clear_history(self, chat_id: int) -> None:
        await self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await self._conn.commit()

    # --- per-chat settings ---------------------------------------------------

    async def get_settings(self, chat_id: int) -> ChatSettings:
        async with self._conn.execute(
            "SELECT mode, web_search FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return ChatSettings(mode="fast", web_search=True)
        return ChatSettings(mode=row[0], web_search=bool(row[1]))

    async def _ensure_row(self, chat_id: int) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,)
        )

    async def set_mode(self, chat_id: int, mode: Mode) -> None:
        await self._ensure_row(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET mode = ? WHERE chat_id = ?", (mode, chat_id)
        )
        await self._conn.commit()

    async def set_web_search(self, chat_id: int, enabled: bool) -> None:
        await self._ensure_row(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET web_search = ? WHERE chat_id = ?",
            (int(enabled), chat_id),
        )
        await self._conn.commit()

    # --- attached files (RAG) ------------------------------------------------

    async def add_file(self, chat_id: int, file_id: str, filename: str) -> None:
        await self._conn.execute(
            "INSERT INTO chat_files (chat_id, file_id, filename, ts) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, file_id, filename, time.time()),
        )
        await self._conn.commit()

    async def get_file_ids(self, chat_id: int) -> list[str]:
        async with self._conn.execute(
            "SELECT file_id FROM chat_files WHERE chat_id = ? ORDER BY ts",
            (chat_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def list_files(self, chat_id: int) -> list[str]:
        """Return attached file names, oldest first."""
        async with self._conn.execute(
            "SELECT filename FROM chat_files WHERE chat_id = ? ORDER BY ts",
            (chat_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def clear_files(self, chat_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM chat_files WHERE chat_id = ?", (chat_id,)
        )
        await self._conn.commit()
