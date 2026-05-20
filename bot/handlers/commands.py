"""Slash commands (DM only). All are admin-gated by the dispatcher middleware."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.openwebui import OpenWebUIClient, OpenWebUIError

router = Router(name="commands")

_HELP = (
    "<b>Local Qwen assistant</b>\n\n"
    "Just send me a message and I'll answer — with web search and memory of our "
    "chat. Send a document to chat about it, or a voice message and I'll "
    "transcribe and answer it. You can also summon me in any chat by mentioning "
    "my @username (guest mode: one question, one answer, no memory there).\n\n"
    "<b>Per-message model flag</b>\n"
    "Add <code>/think</code> (or <code>!t</code>) anywhere in a message for the "
    "slower reasoning model; <code>/fast</code> (<code>!f</code>) forces the quick "
    "one. Put the flag at the end of your message.\n\n"
    "<b>Tools</b> — use them by replying to a message, or with inline text:\n"
    "/summarize — summarize a message, text or URL\n"
    "/translate &lt;language&gt; — translate a message or text\n"
    "/rewrite &lt;style&gt; — rewrite text (shorter, more formal, …)\n\n"
    "<b>Commands</b>\n"
    "/mode — show or set the default model (<code>/mode think</code> | "
    "<code>/mode fast</code>)\n"
    "/web — show or toggle web search (<code>/web on</code> | <code>/web off</code>)\n"
    "/files — list attached documents (<code>/files clear</code> to remove them)\n"
    "/reset (or /new) — forget this chat's history\n"
    "/status — check the model backend\n"
    "/help — this message"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(_HELP, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP, parse_mode="HTML")


@router.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip().lower()
    if arg in ("think", "thinking"):
        await db.set_mode(message.chat.id, "thinking")
        await message.answer("✅ Default model: <b>thinking</b>", parse_mode="HTML")
    elif arg in ("fast", "quick"):
        await db.set_mode(message.chat.id, "fast")
        await message.answer("✅ Default model: <b>fast</b>", parse_mode="HTML")
    else:
        settings = await db.get_settings(message.chat.id)
        await message.answer(
            f"Default model: <b>{settings.mode}</b>\n"
            "Set it with <code>/mode think</code> or <code>/mode fast</code>.",
            parse_mode="HTML",
        )


@router.message(Command("web"))
async def cmd_web(message: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip().lower()
    if arg in ("on", "enable", "true"):
        await db.set_web_search(message.chat.id, True)
        await message.answer("✅ Web search: <b>on</b>", parse_mode="HTML")
    elif arg in ("off", "disable", "false"):
        await db.set_web_search(message.chat.id, False)
        await message.answer("✅ Web search: <b>off</b>", parse_mode="HTML")
    else:
        settings = await db.get_settings(message.chat.id)
        state = "on" if settings.web_search else "off"
        await message.answer(
            f"Web search: <b>{state}</b>\n"
            "Toggle it with <code>/web on</code> or <code>/web off</code>.",
            parse_mode="HTML",
        )


@router.message(Command("files"))
async def cmd_files(message: Message, command: CommandObject, db: Database) -> None:
    if (command.args or "").strip().lower() == "clear":
        await db.clear_files(message.chat.id)
        await message.answer("🗑️ Attached documents removed.")
        return
    names = await db.list_files(message.chat.id)
    if not names:
        await message.answer("No documents attached. Send me one to chat about it.")
        return
    listing = "\n".join(f"  • {n}" for n in names)
    await message.answer(
        f"📎 Attached documents:\n{listing}\n\n"
        "Remove them with <code>/files clear</code>.",
        parse_mode="HTML",
    )


@router.message(Command("reset", "new"))
async def cmd_reset(message: Message, db: Database) -> None:
    await db.clear_history(message.chat.id)
    await message.answer("🧹 Chat history cleared.")


@router.message(Command("status"))
async def cmd_status(
    message: Message, db: Database, client: OpenWebUIClient, config: Config
) -> None:
    settings = await db.get_settings(message.chat.id)
    lines = [
        f"<b>Default model:</b> {settings.mode}",
        f"<b>Web search:</b> {'on' if settings.web_search else 'off'}",
    ]
    try:
        models = await client.list_models()
        lines.append(f"<b>Backend:</b> reachable ({len(models)} models)")
        for name, expected in (
            ("fast", config.model_fast),
            ("thinking", config.model_thinking),
        ):
            mark = "✅" if expected in models else "⚠️ not found"
            lines.append(f"  • {name}: <code>{expected}</code> {mark}")
    except OpenWebUIError as exc:
        lines.append(f"<b>Backend:</b> ⚠️ unreachable — {exc}")
    await message.answer("\n".join(lines), parse_mode="HTML")
