"""Guest-mode handler.

When the admin mentions the bot's @username in any chat, Telegram delivers a
``guest_message`` update. Guest mode is strictly per-message: no chat history,
no member list, and exactly one reply — sent via ``answerGuestQuery``.
"""

from __future__ import annotations

import asyncio
import re

from aiogram import Bot, Router
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from bot.config import Config
from bot.formatting import TELEGRAM_LIMIT, render_html, visible_so_far
from bot.images import user_message
from bot.openwebui import OpenWebUIClient, OpenWebUIError
from bot.prompts import system_prompt
from bot.routing import model_id, route

router = Router(name="guest")


def _strip_mention(text: str, bot_username: str) -> str:
    """Remove the @botusername that summoned the bot."""
    pattern = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
    return pattern.sub(" ", text).strip()


@router.guest_message()
async def handle_guest(
    message: Message,
    bot: Bot,
    client: OpenWebUIClient,
    config: Config,
    bot_username: str,
) -> None:
    raw = message.text or message.caption or ""
    routed = route(_strip_mention(raw, bot_username), default="fast")

    # A photo attached to the mentioning message is sent to the vision model.
    images = None
    if message.photo:
        try:
            buf = await bot.download(message.photo[-1])
            content = buf.read() if buf is not None else b""
            images = [(content, "image/jpeg")]
        except Exception:  # noqa: BLE001 — fall back to a text-only answer
            images = None

    if not routed.text and not images:
        return  # nothing was actually asked

    model = model_id(routed.mode, config.model_fast, config.model_thinking)
    conversation = [system_prompt(), user_message(routed.text, images)]

    try:
        answer = await asyncio.wait_for(
            client.complete_chat(
                model,
                conversation,
                web_search=True,
                chat_id=f"local:telegram-guest-{message.chat.id}",
            ),
            timeout=config.response_timeout,
        )
        answer = visible_so_far(answer) or "The model returned an empty answer."
    except asyncio.TimeoutError:
        answer = "⚠️ The model took too long to answer — try a simpler question."
    except OpenWebUIError as exc:
        answer = f"⚠️ The local model is unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001 — never leave the query unanswered
        answer = f"⚠️ Unexpected error: {exc}"

    answer = answer[:TELEGRAM_LIMIT]
    result = InlineQueryResultArticle(
        id="answer",
        title="Assistant answer",
        description=answer[:120],
        input_message_content=InputTextMessageContent(
            message_text=render_html(answer),
            parse_mode="HTML",
        ),
    )
    await message.answer_guest_query(result=result)
