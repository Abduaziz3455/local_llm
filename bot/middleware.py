"""Admin-only gate.

Registered as an outer middleware on both the ``message`` and ``guest_message``
observers so every incoming interaction is checked before any handler runs:

* DM from a non-admin   → a short "private assistant" reply, then dropped.
* Guest call by a non-admin → dropped silently, so the bot stays invisible
  to everyone except its owner.
* Anything from the admin → passed through untouched.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_user_id: int) -> None:
        self._admin = admin_user_id

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is not None and user.id == self._admin:
            return await handler(event, data)

        # Not the admin — a guest call (has guest_query_id) is dropped silently;
        # a plain DM gets one polite line so a stranger isn't left hanging.
        is_guest = getattr(event, "guest_query_id", None) is not None
        if not is_guest and event.chat.type == "private":
            try:
                await event.answer(
                    "This is a private assistant and only responds to its owner."
                )
            except Exception:  # noqa: BLE001 — never let the gate crash
                pass
        return None
