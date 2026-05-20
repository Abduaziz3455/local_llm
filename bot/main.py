"""Entry point: wires up the dispatcher and runs long polling.

Run with:  python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from bot.config import load_config
from bot.db import Database
from bot.handlers import commands, dm, guest, tools
from bot.middleware import AdminOnlyMiddleware
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
    BotCommand(command="reset", description="Forget this chat's history"),
    BotCommand(command="status", description="Check the model backend"),
]


async def _setup_commands(bot: Bot, admin_user_id: int) -> None:
    """Publish the command menu to the admin only, and clear it for everyone else."""
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

    db = Database(config.db_path)
    await db.connect()
    client = OpenWebUIClient(
        config.openwebui_url, config.openwebui_api_key, config.request_timeout
    )

    me = await bot.get_me()
    log.info("Starting bot @%s (admin user id: %s)", me.username, config.admin_user_id)

    # Publish the slash-command menu to the admin's chat only.
    try:
        await _setup_commands(bot, config.admin_user_id)
        log.info("Command menu registered for admin chat %s", config.admin_user_id)
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

    # Admin-only gate on both message and guest-message updates.
    gate = AdminOnlyMiddleware(config.admin_user_id)
    dp.message.outer_middleware(gate)
    dp.guest_message.outer_middleware(gate)

    # Commands and tools first so they win over the catch-all DM handler.
    dp.include_router(commands.router)
    dp.include_router(tools.router)
    dp.include_router(dm.router)
    dp.include_router(guest.router)

    try:
        await dp.start_polling(
            bot,
            db=db,
            client=client,
            config=config,
            bot_username=me.username,
            allowed_updates=["message", "guest_message"],
        )
    finally:
        await db.close()
        await client.aclose()
        await bot.session.close()
        log.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
