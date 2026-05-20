"""Text shaping for Telegram replies.

The thinking model wraps its reasoning in ``<think>…</think>``; we show only the
final answer. Telegram also caps a message at 4096 characters, so long replies
are split on paragraph/line boundaries.
"""

from __future__ import annotations

import re

TELEGRAM_LIMIT = 4096
_CHUNK = 3900  # stay under the limit with headroom for safety

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Remove complete ``<think>…</think>`` blocks and any trailing open one.

    A trailing unclosed ``<think>`` can appear mid-stream — drop it so the user
    never sees raw reasoning.
    """
    text = _THINK_BLOCK.sub("", text)
    text = _OPEN_THINK.sub("", text)
    return text.strip()


def visible_so_far(text: str) -> str:
    """Best-effort visible answer for a partial (streaming) accumulation.

    While the model is still inside an open ``<think>`` block there is nothing
    to show yet — return an empty string so callers can display a placeholder.
    """
    return strip_thinking(text)


def split_for_telegram(text: str) -> list[str]:
    """Split ``text`` into chunks each within Telegram's message size limit."""
    text = text.strip()
    if len(text) <= TELEGRAM_LIMIT:
        return [text] if text else [""]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _CHUNK:
        window = remaining[:_CHUNK]
        # Prefer to break on a paragraph, then a line, then a space.
        split_at = window.rfind("\n\n")
        if split_at < _CHUNK // 2:
            split_at = window.rfind("\n")
        if split_at < _CHUNK // 2:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = _CHUNK
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
