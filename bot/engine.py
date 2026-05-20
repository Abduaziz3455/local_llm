"""Shared completion runner — streams a reply into a Telegram message.

Used by the DM handler and the per-message tools (summarize / translate /
rewrite). Posts a placeholder, edits it as tokens stream in (throttled to stay
within Telegram's rate limits), then splits any over-long final answer.
"""

from __future__ import annotations

import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot.formatting import TELEGRAM_LIMIT, split_for_telegram, visible_so_far
from bot.openwebui import Message as ChatMessage
from bot.openwebui import OpenWebUIClient, OpenWebUIError

# Throttle message edits so we stay well within Telegram's rate limits.
_EDIT_INTERVAL = 1.3


def thinking_label(thinking: bool) -> str:
    return "🤔 thinking…" if thinking else "💭 …"


async def safe_edit(message: Message, text: str) -> None:
    """Edit a message, ignoring 'not modified' / transient Telegram errors."""
    if not text:
        return
    try:
        await message.edit_text(text[:TELEGRAM_LIMIT])
    except TelegramBadRequest:
        pass


async def stream_reply(
    *,
    bot: Bot,
    client: OpenWebUIClient,
    reply_to: Message,
    model: str,
    conversation: list[ChatMessage],
    web_search: bool = False,
    file_ids: list[str] | None = None,
    thinking: bool = False,
) -> str | None:
    """Stream a completion into a new message replying to ``reply_to``.

    Returns the final visible answer, or ``None`` if an error occurred
    (the error has already been shown to the user).
    """
    chat_id = reply_to.chat.id
    placeholder = await reply_to.answer(thinking_label(thinking))
    accumulated = ""
    last_edit = 0.0
    last_shown = placeholder.text or ""

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            async for delta in client.stream_chat(
                model,
                conversation,
                web_search=web_search,
                file_ids=file_ids,
                chat_id=f"local:telegram-{chat_id}",
            ):
                accumulated += delta
                now = time.monotonic()
                if now - last_edit < _EDIT_INTERVAL:
                    continue
                visible = visible_so_far(accumulated)
                shown = visible or thinking_label(thinking)
                if shown != last_shown:
                    await safe_edit(placeholder, shown)
                    last_shown, last_edit = shown, now
    except OpenWebUIError as exc:
        await safe_edit(placeholder, f"⚠️ {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the bot
        await safe_edit(placeholder, f"⚠️ Unexpected error: {exc}")
        return None

    final = visible_so_far(accumulated)
    if not final:
        await safe_edit(placeholder, "⚠️ The model returned an empty answer.")
        return None

    chunks = split_for_telegram(final)
    await safe_edit(placeholder, chunks[0])
    for chunk in chunks[1:]:
        await reply_to.answer(chunk)
    return final
