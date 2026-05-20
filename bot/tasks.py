"""System prompts for the per-message tools (summarize / translate / rewrite)."""

from __future__ import annotations

SUMMARIZE = (
    "You are a summarizer. Produce a clear, concise summary of the text the user "
    "provides. Lead with a one-sentence gist, then a few bullet points for the key "
    "takeaways. If the user provides a URL, summarize the content at that URL. "
    "Output only the summary."
)


def translate_system(target_language: str) -> str:
    return (
        f"You are a translator. Translate the user's text into {target_language}. "
        "Output only the translation — no notes, no transliteration, no commentary. "
        "Preserve tone, formatting and line breaks."
    )


def rewrite_system(style: str) -> str:
    return (
        f"You are an editor. Rewrite the user's text to be {style}. Keep the "
        "original meaning and language. Output only the rewritten text."
    )
