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

CREATE TABLE IF NOT EXISTS chat_polls (
    chat_id    INTEGER NOT NULL,           -- chat the poll was sent to
    message_id INTEGER NOT NULL,           -- Telegram message id (for stop_poll)
    poll_id    TEXT    NOT NULL,           -- Telegram poll id
    question   TEXT    NOT NULL,
    closed     INTEGER NOT NULL DEFAULT 0, -- 1 once stopped
    ts         REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_polls ON chat_polls(chat_id, ts);
"""


@dataclass(frozen=True)
class ChatSettings:
    mode: Mode
    web_search: bool


class Database:
    def __init__(
        self,
        path: str,
        *,
        max_stored_messages: int = 200,
        file_ttl_hours: float = 24.0,
    ) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None
        # Keep at most this many messages per chat; older ones are pruned on
        # every insert so the table can't grow without bound over months.
        self._max_messages = max(max_stored_messages, 1)
        # Uploaded docs stop being attached for RAG after this many hours.
        self._file_ttl = max(file_ttl_hours, 0.0) * 3600.0

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        # WAL keeps reads and writes from blocking each other and is more
        # crash-resilient — worth it for a process that runs 24/7.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # Drop any files that already expired while the bot was offline.
        await self._prune_expired_files()

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
        # Keep only the most recent N messages for this chat (by rowid, which
        # is unique even if two messages share a timestamp).
        await self._conn.execute(
            "DELETE FROM messages WHERE chat_id = ? AND rowid NOT IN ("
            "SELECT rowid FROM messages WHERE chat_id = ? ORDER BY ts DESC LIMIT ?)",
            (chat_id, chat_id, self._max_messages),
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

    def _file_cutoff(self) -> float:
        """Timestamp before which an uploaded file is considered expired.

        Returns 0.0 (i.e. never expire) when the TTL is disabled.
        """
        return time.time() - self._file_ttl if self._file_ttl > 0 else 0.0

    async def _prune_expired_files(self) -> None:
        """Delete file rows older than the TTL so old docs stop being attached."""
        cutoff = self._file_cutoff()
        if cutoff <= 0:
            return
        await self._conn.execute("DELETE FROM chat_files WHERE ts < ?", (cutoff,))
        await self._conn.commit()

    async def add_file(self, chat_id: int, file_id: str, filename: str) -> None:
        await self._conn.execute(
            "INSERT INTO chat_files (chat_id, file_id, filename, ts) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, file_id, filename, time.time()),
        )
        await self._conn.commit()
        # Opportunistically clear out anything that has aged out.
        await self._prune_expired_files()

    async def get_file_ids(self, chat_id: int) -> list[str]:
        """Return ids of files still within the TTL window, oldest first."""
        async with self._conn.execute(
            "SELECT file_id FROM chat_files WHERE chat_id = ? AND ts >= ? "
            "ORDER BY ts",
            (chat_id, self._file_cutoff()),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def list_files(self, chat_id: int) -> list[str]:
        """Return names of files still within the TTL window, oldest first."""
        async with self._conn.execute(
            "SELECT filename FROM chat_files WHERE chat_id = ? AND ts >= ? "
            "ORDER BY ts",
            (chat_id, self._file_cutoff()),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def clear_files(self, chat_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM chat_files WHERE chat_id = ?", (chat_id,)
        )
        await self._conn.commit()

    # --- polls ---------------------------------------------------------------

    async def record_poll(
        self, chat_id: int, message_id: int, poll_id: str, question: str
    ) -> None:
        """Remember a poll the bot just sent, so it can be closed later."""
        await self._conn.execute(
            "INSERT INTO chat_polls (chat_id, message_id, poll_id, question, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, message_id, poll_id, question, time.time()),
        )
        await self._conn.commit()

    async def get_last_open_poll(self, chat_id: int) -> tuple[int, str] | None:
        """Return ``(message_id, poll_id)`` of the chat's newest open poll, or None."""
        async with self._conn.execute(
            "SELECT message_id, poll_id FROM chat_polls "
            "WHERE chat_id = ? AND closed = 0 ORDER BY ts DESC LIMIT 1",
            (chat_id,),
        ) as cur:
            row = await cur.fetchone()
        return (row[0], row[1]) if row else None

    async def mark_poll_closed(self, chat_id: int, message_id: int) -> None:
        await self._conn.execute(
            "UPDATE chat_polls SET closed = 1 WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        await self._conn.commit()
