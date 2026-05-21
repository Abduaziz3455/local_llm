"""Inbound middlewares: flood control and the admin-only gate.

Both are registered as outer middlewares on the ``message`` and
``guest_message`` observers. Order matters — flood control runs first, so a
burst of spam (even from a stranger) is shed before the admin gate would
otherwise reply to it.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

# Message shown to anyone who is not the configured admin.
NOT_ADMIN_MESSAGE = (
    "🔒 This bot is private — it is accessible only to its admin."
)


def _is_guest(event: Message) -> bool:
    """True if this update is a guest_message (mention) rather than a DM."""
    return getattr(event, "guest_query_id", None) is not None


class ThrottlingMiddleware(BaseMiddleware):
    """Per-user sliding-window rate limit.

    Caps bursts so flooding the bot can't pile up slow backend calls or trip
    Telegram's own rate limits. Over-limit updates are dropped; a private-chat
    sender gets one heads-up per window so they aren't left guessing.
    """

    def __init__(self, limit: int = 5, window: float = 10.0) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}
        self._last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Drop bookkeeping for users idle longer than the window.

        Without this, every distinct sender (including strangers who only ever
        message once) would leave a permanent dict entry — an unbounded leak
        for a process that runs for months.
        """
        for uid in list(self._hits):
            hits = self._hits[uid]
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if not hits:
                del self._hits[uid]
        for uid in list(self._warned):
            if now - self._warned[uid] > self._window:
                del self._warned[uid]

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:  # service messages etc. — nothing to throttle
            return await handler(event, data)

        now = time.monotonic()
        if now - self._last_sweep > self._window:
            self._sweep(now)
            self._last_sweep = now

        hits = self._hits[user.id]
        while hits and now - hits[0] > self._window:
            hits.popleft()

        if len(hits) >= self._limit:
            # Over the limit — drop. Warn at most once per window.
            if now - self._warned.get(user.id, 0.0) > self._window:
                self._warned[user.id] = now
                if not _is_guest(event) and event.chat.type == "private":
                    try:
                        await event.answer(
                            "⏳ Too many messages — give me a moment to catch up."
                        )
                    except Exception:  # noqa: BLE001 — never let the gate crash
                        pass
            return None

        hits.append(now)
        return await handler(event, data)


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_user_ids: frozenset[int]) -> None:
        self._admins = admin_user_ids

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is not None and user.id in self._admins:
            return await handler(event, data)

        # Not the admin — a guest call (has guest_query_id) is dropped silently;
        # a plain DM gets one polite line so a stranger isn't left hanging.
        if not _is_guest(event) and event.chat.type == "private":
            try:
                await event.answer(NOT_ADMIN_MESSAGE)
            except Exception:  # noqa: BLE001 — never let the gate crash
                pass
        return None
