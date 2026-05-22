"""Tracks the in-flight model generation per chat.

A reply is produced in a background ``asyncio.Task`` rather than awaited inside
the message handler — so the handler returns at once and the bot stays free to
process the next update (a ``/stop``, or a follow-up question).

That makes a running generation cancellable:
  * ``/stop`` calls :meth:`cancel`;
  * a new question calls :meth:`run`, which cancels the previous task first.

The cancelled task receives ``asyncio.CancelledError`` at its current await;
:func:`bot.engine.stream_reply` catches it and finalises the partial reply.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

log = logging.getLogger("bot.generation")


class GenerationManager:
    """One in-flight generation task per chat id."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def run(self, chat_id: int, coro: Coroutine) -> None:
        """Start ``coro`` as this chat's generation, cancelling any previous one."""
        self.cancel(chat_id)
        task = asyncio.create_task(coro)
        self._tasks[chat_id] = task
        task.add_done_callback(lambda t: self._cleanup(chat_id, t))

    def cancel(self, chat_id: int) -> bool:
        """Cancel this chat's running generation. Returns True if one was live."""
        task = self._tasks.get(chat_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    def _cleanup(self, chat_id: int, task: asyncio.Task) -> None:
        # Only drop the slot if it still holds *this* task — a newer run() may
        # have already replaced it.
        if self._tasks.get(chat_id) is task:
            del self._tasks[chat_id]
        # Surface unexpected crashes; cancellation is expected and ignored.
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                log.error("Generation task failed: %r", exc)
