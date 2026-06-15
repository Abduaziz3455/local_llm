"""Direct-message handler.

Streaming Q&A with per-chat memory and web search, document upload for RAG
("chat with your PDF"), and image understanding via the multimodal model.
All admin-gated by the dispatcher middleware.

Every reply is produced in a background task via the ``GenerationManager``, so
the bot stays responsive while the model streams — and a running reply can be
cancelled by ``/stop`` or superseded by the next question.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.config import Config
from bot.db import Database
from bot.engine import safe_edit, stream_reply
from bot.generation import GenerationManager
from bot.images import ImagePart, user_message
from bot.llama import LlamaClient
from bot.openwebui import OpenWebUIClient, OpenWebUIError
from bot.polls import maybe_handle_poll
from bot.prompts import system_prompt
from bot.routing import model_id, route

router = Router(name="dm")

# Telegram bots can download files up to 20 MB.
_MAX_FILE_BYTES = 20 * 1024 * 1024


async def _download(bot: Bot, obj) -> bytes:
    """Download a Telegram file object (photo, document, …) to bytes."""
    buf = await bot.download(obj)
    return buf.read() if buf is not None else b""


async def _reply_images(bot: Bot, message: Message) -> list[ImagePart] | None:
    """Image(s) carried by the message this one replies to, if any.

    Lets you reply to an earlier photo with a follow-up question about it.
    """
    replied = message.reply_to_message
    if replied is None:
        return None
    if replied.photo:
        # Photos are ordered smallest→largest; Telegram re-encodes them as JPEG.
        return [(await _download(bot, replied.photo[-1]), "image/jpeg")]
    doc = replied.document
    if doc is not None and (doc.mime_type or "").startswith("image/"):
        return [(await _download(bot, doc), doc.mime_type or "image/jpeg")]
    return None


async def _answer(
    message: Message,
    question: str,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    config: Config,
    images: list[ImagePart] | None = None,
    llama: LlamaClient | None = None,
) -> None:
    """Route a question, run the model, stream the reply, and save history.

    ``images`` is an optional list of ``(raw_bytes, mime_type)`` pairs; when
    present the user turn is built as multimodal content so the vision model
    sees the picture(s) alongside the text.

    When ``llama`` is given and the message has no image, a poll tool-call is
    attempted first: if the model decides to create or close a poll, that is
    executed and the normal chat answer is skipped.
    """
    chat_id = message.chat.id
    settings = await db.get_settings(chat_id)
    routed = route(question, settings.mode)
    if not routed.text and not images:
        await message.answer("Add a question along with that flag.")
        return

    model = model_id(routed.mode, config.model_fast, config.model_thinking)
    history = await db.get_history(chat_id, config.history_turns)

    # Tool-calling path: poll create/close (DM-only). Runs first; the cheap
    # keyword pre-filter inside maybe_handle_poll means ordinary chat pays no
    # extra latency. Images (an attached/replied menu) and recent history are
    # passed so the model can extract poll options from a picture or context.
    if llama is not None and config.polls_enabled and routed.text:
        confirmation = await maybe_handle_poll(
            message, routed.text, bot=bot, db=db, llama=llama,
            model=config.poll_model, images=images, history=history,
        )
        if confirmation is not None:
            await message.answer(confirmation)
            await db.add_message(chat_id, "user", routed.text)
            await db.add_message(chat_id, "assistant", confirmation)
            return

    conversation = [
        system_prompt(),
        *history,
        user_message(routed.text, images),
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
        timeout=config.response_timeout,
    )
    if final is not None:
        # History is text-only — store the caption, or a marker when an image
        # was sent without one, so later turns keep coherent context.
        history_text = routed.text or ("[sent an image]" if images else routed.text)
        await db.add_message(chat_id, "user", history_text)
        await db.add_message(chat_id, "assistant", final)


@router.message(F.text, F.chat.type == ChatType.PRIVATE)
async def handle_text(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    gen.run(
        message.chat.id,
        _answer_text(message, bot=bot, db=db, client=client, llama=llama,
                     config=config),
    )


async def _answer_text(
    message: Message,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
) -> None:
    """Answer a text message, pulling in any image it replies to."""
    try:
        images = await _reply_images(bot, message)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"⚠️ Could not read the replied image: {exc}")
        return
    await _answer(
        message, message.text or "", bot=bot, db=db, client=client,
        config=config, images=images, llama=llama,
    )


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
    llama: LlamaClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    doc = message.document
    if doc.file_size and doc.file_size > _MAX_FILE_BYTES:
        await message.answer("⚠️ That file is too large — the limit is about 20 MB.")
        return
    gen.run(
        message.chat.id,
        _process_document(message, bot=bot, db=db, client=client, llama=llama,
                          config=config),
    )


async def _process_document(
    message: Message,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
) -> None:
    """Either feed an image-document to the vision model, or upload a document
    to Open WebUI so later questions can use it for RAG."""
    doc = message.document
    name = doc.file_name or "file"
    mime = doc.mime_type or ""

    # An image sent as an uncompressed document — hand it straight to the
    # vision model rather than the RAG pipeline, which can't read pictures.
    if mime.startswith("image/"):
        try:
            content = await _download(bot, doc)
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"⚠️ Could not read the image: {exc}")
            return
        await _answer(
            message, message.caption or "", bot=bot, db=db, client=client,
            config=config, images=[(content, mime)], llama=llama,
        )
        return

    status_msg = await message.answer(f"📎 Uploading {name}…")
    try:
        content = await _download(bot, doc)
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
            message, message.caption, bot=bot, db=db, client=client,
            config=config, llama=llama,
        )


@router.message(F.voice | F.audio, F.chat.type == ChatType.PRIVATE)
async def handle_audio(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    media = message.voice or message.audio
    if media is None:
        return
    if media.file_size and media.file_size > _MAX_FILE_BYTES:
        await message.answer("⚠️ That audio is too large — the limit is about 20 MB.")
        return
    gen.run(
        message.chat.id,
        _process_audio(message, bot=bot, db=db, client=client, llama=llama,
                       config=config),
    )


async def _process_audio(
    message: Message,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
) -> None:
    """Transcribe a voice message / audio file, then answer it as a question."""
    media = message.voice or message.audio
    if media is None:
        return

    content_type = media.mime_type or "audio/ogg"
    filename = getattr(media, "file_name", None) or "voice.oga"
    status_msg = await message.answer("🎙️ Transcribing…")
    try:
        content = await _download(bot, media)
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
        message, transcript, bot=bot, db=db, client=client, config=config,
        llama=llama,
    )


@router.message(F.photo, F.chat.type == ChatType.PRIVATE)
async def handle_photo(
    message: Message,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
    gen: GenerationManager,
) -> None:
    # ``message.photo`` is ordered smallest→largest — take the highest-res one.
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > _MAX_FILE_BYTES:
        await message.answer("⚠️ That image is too large — the limit is about 20 MB.")
        return
    gen.run(
        message.chat.id,
        _answer_photo(message, bot=bot, db=db, client=client, llama=llama,
                      config=config),
    )


async def _answer_photo(
    message: Message,
    *,
    bot: Bot,
    db: Database,
    client: OpenWebUIClient,
    llama: LlamaClient,
    config: Config,
) -> None:
    """Send a photo to the multimodal model for image understanding.

    Any caption is used as the question; without one the model is simply
    asked to describe the picture. A poll-related caption (e.g. "create a poll
    from this menu") routes through the poll tool path, which can read the image.
    """
    try:
        content = await _download(bot, message.photo[-1])
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"⚠️ Could not read the image: {exc}")
        return
    # Telegram always re-encodes photos as JPEG.
    await _answer(
        message, message.caption or "", bot=bot, db=db, client=client,
        config=config, images=[(content, "image/jpeg")], llama=llama,
    )


@router.message(F.chat.type == ChatType.PRIVATE)
async def handle_unsupported(message: Message) -> None:
    """Stickers, video, etc. — not supported."""
    await message.answer(
        "I can handle text, photos, documents and voice messages. "
        "Send me one of those."
    )
