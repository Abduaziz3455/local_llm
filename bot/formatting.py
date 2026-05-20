"""Text shaping for Telegram replies.

The thinking model wraps its reasoning in ``<think>…</think>``; we show only the
final answer. Telegram also caps a message at 4096 characters, so long replies
are split on paragraph/line boundaries.
"""

from __future__ import annotations

import html as _html
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


# --- Markdown → Telegram HTML ------------------------------------------------
# The model emits CommonMark; Telegram renders only a small HTML subset. We
# convert the elements a chat model actually produces and let anything else
# (tables, images) fall through as plain text. Code spans are pulled out first
# so their contents are never treated as markup.

_FENCE_RE = re.compile(r"```[ \t]*([\w+#-]*)[ \t]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_HR_RE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^([ \t]*)[*+-][ \t]+", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_BOLD_ALT_RE = re.compile(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_ITALIC_ALT_RE = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def render_html(text: str) -> str:
    """Convert the model's Markdown into the HTML subset Telegram renders.

    Output is always balanced HTML, safe to send with ``parse_mode="HTML"``.
    Callers should still keep a plain-text fallback in case a future construct
    slips through, but in practice the tags emitted here are always paired.
    """
    fences: list[tuple[str, str]] = []
    inlines: list[str] = []

    def _stash_fence(m: re.Match) -> str:
        fences.append((m.group(1), m.group(2)))
        return f"\x00F{len(fences) - 1}\x00"

    def _stash_inline(m: re.Match) -> str:
        inlines.append(m.group(1))
        return f"\x00C{len(inlines) - 1}\x00"

    # 1. Lift code out so markup and escaping never touch it.
    text = _FENCE_RE.sub(_stash_fence, text)
    text = _INLINE_CODE_RE.sub(_stash_inline, text)

    # 2. Escape the remaining prose — only & < > matter for Telegram HTML.
    text = _html.escape(text, quote=False)

    # 3. Block-level: horizontal rules, headings, bullet markers.
    text = _HR_RE.sub("──────────", text)
    text = _HEADING_RE.sub(r"<b>\1</b>", text)
    text = _BULLET_RE.sub(r"\1• ", text)

    # 4. Inline: bold before italic so ** is consumed first.
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_ALT_RE.sub(r"<b>\1</b>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_ALT_RE.sub(r"<i>\1</i>", text)

    def _link(m: re.Match) -> str:
        return f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>'

    text = _LINK_RE.sub(_link, text)

    # 5. Restore code, escaping its contents now (it skipped step 2).
    def _restore_inline(m: re.Match) -> str:
        return f"<code>{_html.escape(inlines[int(m.group(1))], quote=False)}</code>"

    def _restore_fence(m: re.Match) -> str:
        lang, code = fences[int(m.group(1))]
        code = _html.escape(code.rstrip('\n'), quote=False)
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        return f"<pre>{code}</pre>"

    text = re.sub(r"\x00C(\d+)\x00", _restore_inline, text)
    text = re.sub(r"\x00F(\d+)\x00", _restore_fence, text)
    return text


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
