"""Helpers for building multimodal (image) chat messages.

The local model is multimodal: it reads images passed as OpenAI-shaped content
parts. An image is sent inline as a base64 ``data:`` URL — Open WebUI forwards
the ``content`` list to the model unchanged.
"""

from __future__ import annotations

import base64

from bot.openwebui import Message

# An image to attach: its raw bytes and MIME type, e.g. (b"...", "image/jpeg").
ImagePart = tuple[bytes, str]


def _data_url(content: bytes, mime: str) -> str:
    """Encode raw image bytes as an OpenAI-style base64 data URL."""
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


def user_message(text: str, images: list[ImagePart] | None = None) -> Message:
    """Build a user turn — a plain string, or multimodal content if images are
    given (a text part first, then one ``image_url`` part per image)."""
    if not images:
        return {"role": "user", "content": text}
    parts: list[dict] = [{"type": "text", "text": text or "Describe this image."}]
    for content, mime in images:
        parts.append(
            {"type": "image_url", "image_url": {"url": _data_url(content, mime)}}
        )
    return {"role": "user", "content": parts}
