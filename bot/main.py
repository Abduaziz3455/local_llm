"""Entry point: wires up the dispatcher and runs long polling.

Run with:  python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import load_config
from bot.db import Database
from bot.handlers import commands, dm, guest, tools
from bot.middleware import AdminOnlyMiddleware
from bot.openwebui import OpenWebUIClient, OpenWebUIError

log = logging.getLogger("bot")


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
