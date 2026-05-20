"""Model routing — decide fast vs thinking for a single message.

Default comes from the per-chat setting; an inline flag overrides it for that
message only:
  * ``/think`` or ``!t``  → thinking model
  * ``/fast``  or ``!f``  → fast model
The flag is stripped from the text before it reaches the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bot.db import Mode

# Flags may appear at the start or end of the message; matched case-insensitively.
_THINK_FLAG = re.compile(r"(?:^|\s)(?:/think|!t)(?:\s|$)", re.IGNORECASE)
_FAST_FLAG = re.compile(r"(?:^|\s)(?:/fast|!f)(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Routed:
    mode: Mode          # 'fast' | 'thinking'
    text: str           # message with the flag removed, stripped


def route(text: str, default: Mode) -> Routed:
    """Pick a model mode for ``text`` given the chat's ``default`` mode."""
    mode: Mode = default
    cleaned = text

    if _THINK_FLAG.search(cleaned):
        mode = "thinking"
        cleaned = _THINK_FLAG.sub(" ", cleaned)
    elif _FAST_FLAG.search(cleaned):
        mode = "fast"
        cleaned = _FAST_FLAG.sub(" ", cleaned)

    return Routed(mode=mode, text=cleaned.strip())


def model_id(mode: Mode, model_fast: str, model_thinking: str) -> str:
    """Map a mode to the configured Open WebUI model-entry id."""
    return model_thinking if mode == "thinking" else model_fast
