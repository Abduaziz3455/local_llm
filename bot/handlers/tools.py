"""Per-message tools: /summarize, /translate, /rewrite (DM only).

Each is a one-off task — no chat history is read or written. The input is the
message being replied to, or text given as the command argument.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.engine import stream_reply
from bot.generation import GenerationManager
from bot.openwebui import OpenWebUIClient
from bot.routing import model_id
from bot.tasks import SUMMARIZE, rewrite_system, translate_system

router = Router(name="tools")


def _replied_text(message: Message) -> str | None:
    """Text (or caption) of the message this command replies to, if any."""
    replied = message.reply_to_message
    if replied is None:
        return None
    return replied.text or replied.caption


async def _run_tool(
    message: Message,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
    system: str,
    user_text: str,
    web_search: bool,
) -> None:
    settings = await db.get_settings(message.chat.id)
    model = model_id(settings.mode, config.model_fast, config.model_thinking)
    conversation = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
    await stream_reply(
        bot=bot,
        client=client,
        reply_to=message,
        model=model,
        conversation=conversation,
        web_search=web_search,
        thinking=settings.mode == "thinking",
        timeout=config.response_timeout,
    )


@router.message(Command("summarize", "tldr"))
async def cmd_summarize(
    message: Message,
    command: CommandObject,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    text = _replied_text(message) or (command.args or "").strip()
    if not text:
        await message.answer(
            "Reply to a message with /summarize, or write "
            "<code>/summarize &lt;text or URL&gt;</code>.",
            parse_mode="HTML",
        )
        return
    gen.run(message.chat.id, _run_tool(
        message, bot=bot, db=db, client=client, config=config,
        system=SUMMARIZE, user_text=text, web_search=True,
    ))


@router.message(Command("translate", "tr"))
async def cmd_translate(
    message: Message,
    command: CommandObject,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    args = (command.args or "").split(maxsplit=1)
    replied = _replied_text(message)
    if replied is not None:
        target = args[0] if args else "English"
        text = replied
    elif len(args) >= 2:
        target, text = args[0], args[1]
    else:
        await message.answer(
            "Reply to a message with <code>/translate &lt;language&gt;</code>, "
            "or write <code>/translate &lt;language&gt; &lt;text&gt;</code>.",
            parse_mode="HTML",
        )
        return
    gen.run(message.chat.id, _run_tool(
        message, bot=bot, db=db, client=client, config=config,
        system=translate_system(target), user_text=text, web_search=False,
    ))


@router.message(Command("rewrite"))
async def cmd_rewrite(
    message: Message,
    command: CommandObject,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    args = (command.args or "").split(maxsplit=1)
    replied = _replied_text(message)
    if replied is not None:
        # When replying, the whole argument is the style (may be multi-word).
        style = (command.args or "").strip() or "clearer and more concise"
        text = replied
    elif len(args) >= 2:
        style, text = args[0], args[1]
    else:
        await message.answer(
            "Reply to a message with <code>/rewrite &lt;style&gt;</code>, "
            "or write <code>/rewrite &lt;style&gt; &lt;text&gt;</code>.\n"
            "Example styles: <i>shorter</i>, <i>more formal</i>, <i>friendlier</i>.",
            parse_mode="HTML",
        )
        return
    gen.run(message.chat.id, _run_tool(
        message, bot=bot, db=db, client=client, config=config,
        system=rewrite_system(style), user_text=text, web_search=False,
    ))
