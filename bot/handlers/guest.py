"""Guest-mode handler.

When the admin mentions the bot's @username in any chat, Telegram delivers a
``guest_message`` update. Guest mode is strictly per-message: no chat history,
no member list, and exactly one reply — sent via ``answerGuestQuery``.
"""

from __future__ import annotations

import re

from aiogram import Router
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from bot.config import Config
from bot.formatting import TELEGRAM_LIMIT, render_html, visible_so_far
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
    client: OpenWebUIClient,
    config: Config,
    bot_username: str,
) -> None:
    raw = message.text or message.caption or ""
    routed = route(_strip_mention(raw, bot_username), default="fast")
    if not routed.text:
        return  # nothing was actually asked

    model = model_id(routed.mode, config.model_fast, config.model_thinking)
    conversation = [system_prompt(), {"role": "user", "content": routed.text}]

    try:
        answer = await client.complete_chat(
            model,
            conversation,
            web_search=True,
            chat_id=f"local:telegram-guest-{message.chat.id}",
        )
        answer = visible_so_far(answer) or "The model returned an empty answer."
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
