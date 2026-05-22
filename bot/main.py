"""Entry point: wires up the dispatcher and runs long polling.

Run with:  python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from bot.config import load_config
from bot.db import Database
from bot.generation import GenerationManager
from bot.handlers import commands, dm, guest, tools
from bot.middleware import AdminOnlyMiddleware, ThrottlingMiddleware
from bot.openwebui import OpenWebUIClient, OpenWebUIError

log = logging.getLogger("bot")

# Command menu shown in Telegram's "/" picker. Registered for the admin's chat
# only — non-admins get an empty menu so the bot's surface stays private.
_ADMIN_COMMANDS = [
    BotCommand(command="help", description="Show usage help"),
    BotCommand(command="mode", description="Show or set the default model"),
    BotCommand(command="web", description="Toggle web search"),
    BotCommand(command="summarize", description="Summarize a message, text or URL"),
    BotCommand(command="translate", description="Translate a message or text"),
    BotCommand(command="rewrite", description="Rewrite text in a given style"),
    BotCommand(command="files", description="List or clear attached documents"),
    BotCommand(command="stop", description="Stop the reply being generated"),
    BotCommand(command="reset", description="Forget this chat's history"),
    BotCommand(command="status", description="Check the model backend"),
]


async def _heartbeat(path: Path, interval: float = 30.0) -> None:
    """Touch ``path`` periodically so the container healthcheck can detect a
    hung event loop (the file's mtime stops advancing if polling stalls)."""
    while True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(time.time()))
        except OSError as exc:  # non-fatal — never let the heartbeat crash polling
            log.warning("Could not write heartbeat file: %s", exc)
        await asyncio.sleep(interval)


async def _setup_commands(bot: Bot, admin_user_ids: frozenset[int]) -> None:
    """Publish the command menu to admins only, and clear it for everyone else."""
    for admin_user_id in admin_user_ids:
        await bot.set_my_commands(
            _ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_user_id)
        )
    # Wipe any previously-set default-scope commands so strangers see nothing.
    await bot.delete_my_commands(scope=BotCommandScopeDefault())


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()

    db = Database(
        config.db_path,
        max_stored_messages=config.max_stored_messages,
        file_ttl_hours=config.file_ttl_hours,
    )
    await db.connect()
    client = OpenWebUIClient(
        config.openwebui_url, config.openwebui_api_key, config.request_timeout
    )
    # Tracks the in-flight generation per chat so /stop and follow-up
    # questions can cancel a reply that's still streaming.
    gen = GenerationManager()

    me = await bot.get_me()
    log.info(
        "Starting bot @%s (admin user ids: %s)",
        me.username,
        ", ".join(str(uid) for uid in sorted(config.admin_user_ids)),
    )

    # Publish the slash-command menu to admin chats only.
    try:
        await _setup_commands(bot, config.admin_user_ids)
        log.info(
            "Command menu registered for %d admin chat(s)",
            len(config.admin_user_ids),
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal; the bot still works
        log.warning("Could not register command menu: %s", exc)

    # Startup backend probe — warn loudly but still start, so the bot can report
    # the problem to the user instead of crash-looping.
    try:
        models = await client.list_models()
        log.info("Open WebUI reachable — %d model(s) available", len(models))
        for label, model_id in (
            ("fast", config.model_fast),
            ("thinking", config.model_thinking),
        ):
            if model_id not in models:
                log.warning(
                    "Configured %s model %r not found in Open WebUI. "
                    "Available: %s",
                    label,
                    model_id,
                    models,
                )
    except OpenWebUIError as exc:
        log.warning("Open WebUI not reachable at startup: %s", exc)

    # Flood control first (sheds bursts before the gate would reply to them),
    # then the admin-only gate — both on message and guest-message updates.
    flood = ThrottlingMiddleware()
    dp.message.outer_middleware(flood)
    dp.guest_message.outer_middleware(flood)

    gate = AdminOnlyMiddleware(config.admin_user_ids)
    dp.message.outer_middleware(gate)
    dp.guest_message.outer_middleware(gate)

    # Commands and tools first so they win over the catch-all DM handler.
    dp.include_router(commands.router)
    dp.include_router(tools.router)
    dp.include_router(dm.router)
    dp.include_router(guest.router)

    heartbeat = asyncio.create_task(
        _heartbeat(Path(config.db_path).with_name("heartbeat"))
    )
    try:
        await dp.start_polling(
            bot,
            db=db,
            client=client,
            config=config,
            gen=gen,
            bot_username=me.username,
            allowed_updates=["message", "guest_message"],
        )
    finally:
        heartbeat.cancel()
        await db.close()
        await client.aclose()
        await bot.session.close()
        log.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
