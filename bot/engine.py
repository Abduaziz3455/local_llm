"""Shared completion runner — streams a reply into a Telegram message.

Used by the DM handler and the per-message tools (summarize / translate /
rewrite). Posts a placeholder, edits it as tokens stream in (throttled to stay
within Telegram's rate limits), then splits any over-long final answer.
"""

from __future__ import annotations

import asyncio
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot.formatting import (
    TELEGRAM_LIMIT,
    render_html,
    split_for_telegram,
    visible_so_far,
)
from bot.openwebui import Message as ChatMessage
from bot.openwebui import OpenWebUIClient, OpenWebUIError

# Throttle message edits so we stay well within Telegram's rate limits.
_EDIT_INTERVAL = 1.3


def thinking_label(thinking: bool) -> str:
    return "🤔 thinking…" if thinking else "💭 …"


async def safe_edit(message: Message, text: str) -> None:
    """Edit a message with plain text, ignoring transient Telegram errors."""
    if not text:
        return
    try:
        await message.edit_text(text[:TELEGRAM_LIMIT])
    except TelegramBadRequest:
        pass


async def _send_html(send, plain: str) -> None:
    """Render ``plain`` as Telegram HTML via ``send`` (edit_text / answer).

    Falls back to the unformatted text if Telegram rejects the markup, so a
    bad conversion degrades gracefully instead of dropping the reply.
    """
    if not plain:
        return
    try:
        await send(render_html(plain), parse_mode="HTML")
    except TelegramBadRequest:
        try:
            await send(plain[:TELEGRAM_LIMIT])
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
    timeout: float | None = None,
) -> str | None:
    """Stream a completion into a new message replying to ``reply_to``.

    Returns the final visible answer, or ``None`` if an error occurred
    (the error has already been shown to the user).

    ``timeout`` caps how long one generation may run; when it elapses the
    partial reply is kept and flagged. If the surrounding task is cancelled
    (``/stop`` or a superseding question) the partial reply is likewise kept
    and flagged — cancellation never crashes the bot.
    """
    chat_id = reply_to.chat.id
    placeholder = await reply_to.answer(thinking_label(thinking))
    accumulated = ""
    last_edit = 0.0
    last_shown = placeholder.text or ""
    stats: dict = {}
    timed_out = False
    stopped = False

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            async with asyncio.timeout(timeout):
                async for delta in client.stream_chat(
                    model,
                    conversation,
                    web_search=web_search,
                    file_ids=file_ids,
                    chat_id=f"local:telegram-{chat_id}",
                    stats=stats,
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
    except asyncio.TimeoutError:
        # The hard time cap fired — keep whatever streamed so far.
        timed_out = True
    except asyncio.CancelledError:
        # /stop, or a new question superseded this one — keep the partial.
        stopped = True
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the bot
        await safe_edit(placeholder, f"⚠️ Unexpected error: {exc}")
        return None

    final = visible_so_far(accumulated)
    if not final:
        if stopped:
            await safe_edit(placeholder, "⏹ Stopped.")
        elif timed_out:
            await safe_edit(placeholder, "⚠️ Stopped — the model took too long.")
        else:
            await safe_edit(placeholder, "⚠️ The model returned an empty answer.")
        return None

    if timed_out:
        final += "\n\n_⚠️ Stopped — the response hit the time limit._"
    elif stopped:
        final += "\n\n_⏹ Stopped._"
    # The model stopped because it ran out of room (context window full), not
    # because it finished — flag it so the user isn't left with a sentence that
    # just trails off mid-word.
    elif stats.get("finish_reason") == "length":
        final += (
            "\n\n_⚠️ Reply cut off — the model hit its length limit. "
            "Send “continue” to get the rest, or /reset to free up context._"
        )

    # Split on plain text (visible-length boundaries), then format each chunk.
    chunks = split_for_telegram(final)
    await _send_html(placeholder.edit_text, chunks[0])
    for chunk in chunks[1:]:
        await _send_html(reply_to.answer, chunk)
    return final
