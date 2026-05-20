"""Direct-message handler.

Streaming Q&A with per-chat memory and web search, plus document upload for
RAG ("chat with your PDF"). All admin-gated by the dispatcher middleware.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.engine import safe_edit, stream_reply
from bot.openwebui import OpenWebUIClient, OpenWebUIError
from bot.prompts import system_prompt
from bot.routing import model_id, route

router = Router(name="dm")

# Telegram bots can download files up to 20 MB.
_MAX_FILE_BYTES = 20 * 1024 * 1024


async def _answer(
    message: Message,
    question: str,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
) -> None:
    """Route a question, run the model, stream the reply, and save history."""
    chat_id = message.chat.id
    settings = await db.get_settings(chat_id)
    routed = route(question, settings.mode)
    if not routed.text:
        await message.answer("Add a question along with that flag.")
        return

    model = model_id(routed.mode, config.model_fast, config.model_thinking)
    history = await db.get_history(chat_id, config.history_turns)
    conversation = [
        system_prompt(),
        *history,
        {"role": "user", "content": routed.text},
    ]
    file_ids = await db.get_file_ids(chat_id)

    final = await stream_reply(
        bot=bot,
        client=client,
        reply_to=message,
        model=model,
        conversation=conversation,
        web_search=settings.web_search,
        file_ids=file_ids,
        thinking=routed.mode == "thinking",
    )
    if final is not None:
        await db.add_message(chat_id, "user", routed.text)
        await db.add_message(chat_id, "assistant", final)


@router.message(F.text, F.chat.type == ChatType.PRIVATE)
async def handle_text(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
) -> None:
    await _answer(message, message.text or "", bot=bot, db=db, client=client, config=config)


async def _wait_processed(
    client: OpenWebUIClient, file_id: str, attempts: int = 20, delay: float = 2.0
) -> bool:
    """Poll Open WebUI until the uploaded file is indexed.

    Returns False only on an explicit failure; on timeout or a missing status
    endpoint it returns True, since the file is usually usable anyway.
    """
    for _ in range(attempts):
        try:
            status = (await client.file_process_status(file_id)).lower()
        except OpenWebUIError:
            return True
        if status in ("completed", "success", "done", "ok"):
            return True
        if status in ("failed", "error"):
            return False
        await asyncio.sleep(delay)
    return True


@router.message(F.document, F.chat.type == ChatType.PRIVATE)
async def handle_document(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
) -> None:
    """Upload a document to Open WebUI so later questions can use it for RAG."""
    doc = message.document
    name = doc.file_name or "file"
    if doc.file_size and doc.file_size > _MAX_FILE_BYTES:
        await message.answer("⚠️ That file is too large — the limit is about 20 MB.")
        return

    status_msg = await message.answer(f"📎 Uploading {name}…")
    try:
        buf = await bot.download(doc)
        content = buf.read() if buf is not None else b""
        file_id = await client.upload_file(name, content)
    except OpenWebUIError as exc:
        await safe_edit(status_msg, f"⚠️ Upload failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status_msg, f"⚠️ Could not read the file: {exc}")
        return

    await safe_edit(status_msg, f"📎 Indexing {name}…")
    if not await _wait_processed(client, file_id):
        await safe_edit(status_msg, f"⚠️ Open WebUI failed to process {name}.")
        return

    await db.add_file(message.chat.id, file_id, name)
    await safe_edit(status_msg, f"📎 {name} is ready — ask me anything about it.")

    # A caption on the document is treated as the first question about it.
    if message.caption:
        await _answer(
            message, message.caption, bot=bot, db=db, client=client, config=config
        )


@router.message(F.voice | F.audio, F.chat.type == ChatType.PRIVATE)
async def handle_audio(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
) -> None:
    """Transcribe a voice message / audio file, then answer it as a question."""
    media = message.voice or message.audio
    if media is None:
        return
    if media.file_size and media.file_size > _MAX_FILE_BYTES:
        await message.answer("⚠️ That audio is too large — the limit is about 20 MB.")
        return

    content_type = media.mime_type or "audio/ogg"
    filename = getattr(media, "file_name", None) or "voice.oga"
    status_msg = await message.answer("🎙️ Transcribing…")
    try:
        buf = await bot.download(media)
        content = buf.read() if buf is not None else b""
        transcript = await client.transcribe_audio(filename, content, content_type)
    except OpenWebUIError as exc:
        await safe_edit(status_msg, f"⚠️ {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        await safe_edit(status_msg, f"⚠️ Could not read the audio: {exc}")
        return

    if not transcript:
        await safe_edit(status_msg, "⚠️ Couldn't make out any speech in that audio.")
        return

    await safe_edit(status_msg, f"🎙️ {transcript}")
    await _answer(
        message, transcript, bot=bot, db=db, client=client, config=config
    )


@router.message(F.chat.type == ChatType.PRIVATE)
async def handle_unsupported(message: Message) -> None:
    """Photos, stickers, video, etc. — not supported."""
    await message.answer(
        "I can handle text, documents and voice messages. "
        "Send me one of those."
    )
