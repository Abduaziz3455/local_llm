"""Poll creator/editor — the bot's first tool-calling feature.

Flow (DM only): when a user message looks poll-related, ask the tool model
(Gemma-4-12b via :mod:`bot.llama`) to decide between two tools and supply
arguments, then execute the result with the Telegram Bot API:

    create_poll  -> bot.send_poll(...)          (a brand-new poll)
    close_poll   -> bot.stop_poll(chat_id, mid) (closes the chat's last poll)

Why only create + close: the Telegram Bot API cannot edit a live poll's
question or options after it is sent — it can only stop it. "Editing" a poll
therefore means closing it and creating a new one, which the model can do in
two turns.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Bot
from aiogram.types import InputPollOption, Message

from bot.db import Database
from bot.images import ImagePart, user_message
from bot.llama import LlamaClient, LlamaError, parse_tool_calls

log = logging.getLogger("bot.polls")

# Telegram poll limits.
_MAX_OPTIONS = 10
_MIN_OPTIONS = 2
_Q_LIMIT = 300
_OPT_LIMIT = 100
_DESC_LIMIT = 200       # poll description
_EXPL_LIMIT = 200       # quiz explanation
_MIN_PERIOD = 5         # auto-close: Bot API open_period range is 5..600 seconds
_MAX_PERIOD = 600

# Cheap pre-filter: only spend an LLM call when the message plausibly concerns a
# poll. Covers English + Uzbek (Latin) + common Russian loanword "opros".
_POLL_HINT = re.compile(
    r"\b(poll|polls|survey|vote|voting|voted|quiz|"
    r"so['’ʼ]?rovnoma|so['’ʼ]?rov|ovoz|viktorina|opros|"
    r"golosovani|test\s+savol)\w*",
    re.IGNORECASE,
)

_SYSTEM = (
    "You manage Telegram polls. Decide if the user wants to CREATE a poll or "
    "CLOSE/stop the current poll. "
    "Call create_poll when they ask to make/start/set up a poll, survey, vote "
    "or quiz. Fill question and options, and set ONLY the extra settings the "
    "user actually asks for:\n"
    "- is_anonymous: false to show who voted, true to hide voters.\n"
    "- allows_multiple_answers: true if voters may pick several options.\n"
    "- allows_revoting: true if voters may change their vote.\n"
    "- allow_adding_options: true if participants may suggest new options.\n"
    "- shuffle_options: true to randomise option order per voter.\n"
    "- hide_results_until_closes: true to hide results until the poll closes.\n"
    "- description: a short extra line under the question, if given.\n"
    "- type='quiz' with correct_option_ids (0-based indexes of the correct "
    "answer(s)) and an optional explanation, when there is a right answer.\n"
    "- auto_close_seconds: close automatically after N seconds (5-600) if the "
    "user wants a timed poll.\n"
    "If the options are not listed explicitly but appear in an attached image "
    "(e.g. a menu or flyer) or in the earlier conversation, EXTRACT them "
    "yourself and use them as the poll options — do not ask the user to resend "
    "anything you can already see. "
    "Call close_poll when they ask to close/stop/end the current or last poll. "
    "If the message is NOT about creating or closing a poll, do NOT call any "
    "tool — reply with exactly the word NONE. "
    "The user may write in English or Uzbek."
)

CREATE_POLL = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            "Create a new poll/survey/quiz in the chat. Works in any language."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The poll question."},
                "description": {
                    "type": "string",
                    "description": "Optional short text shown under the question.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The answer options (2-10).",
                },
                "is_anonymous": {
                    "type": "boolean",
                    "description": "False shows who voted; true hides voters.",
                },
                "allows_multiple_answers": {
                    "type": "boolean",
                    "description": "True if voters may pick several options.",
                },
                "allows_revoting": {
                    "type": "boolean",
                    "description": "True if voters may change their vote.",
                },
                "allow_adding_options": {
                    "type": "boolean",
                    "description": "True if participants may suggest new options.",
                },
                "shuffle_options": {
                    "type": "boolean",
                    "description": "True to show options in random order per voter.",
                },
                "hide_results_until_closes": {
                    "type": "boolean",
                    "description": "True to hide results until the poll is closed.",
                },
                "type": {
                    "type": "string",
                    "enum": ["regular", "quiz"],
                    "description": "'quiz' when there is a correct answer.",
                },
                "correct_option_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Quiz only: 0-based index(es) of the correct option(s).",
                },
                "explanation": {
                    "type": "string",
                    "description": "Quiz only: text shown after the user answers.",
                },
                "auto_close_seconds": {
                    "type": "integer",
                    "description": "Auto-close the poll after this many seconds (5-600).",
                },
            },
            "required": ["question", "options"],
        },
    },
}

CLOSE_POLL = {
    "type": "function",
    "function": {
        "name": "close_poll",
        "description": (
            "Close/stop the most recent open poll in this chat so voting ends."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

TOOLS = [CREATE_POLL, CLOSE_POLL]


def looks_poll_related(text: str) -> bool:
    """True if ``text`` is worth sending to the tool model (cheap pre-filter)."""
    return bool(text) and bool(_POLL_HINT.search(text))


def _clean_options(raw: Any) -> list[str]:
    """Normalise the model's options into a valid Telegram option list."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s:
            out.append(s[:_OPT_LIMIT])
    return out[:_MAX_OPTIONS]


def _opt_bool(args: dict, key: str) -> bool | None:
    """Read a boolean the model may have set; None if it left it unspecified."""
    v = args.get(key)
    return v if isinstance(v, bool) else None


def build_poll_kwargs(args: dict) -> tuple[str, list[str], dict, list[str]]:
    """Turn the model's tool arguments into validated send_poll arguments.

    Returns ``(question, options, kwargs, warnings)``. Applies the screenshot's
    defaults where the Bot API allows it, resolves quiz conflicts, and clamps
    values to Telegram's limits. Pure (no I/O) so it can be unit-tested.

    Only settings the user actually asked for are forwarded — except anonymity,
    which defaults to "show who voted" (is_anonymous=False) to match the UI.
    """
    warnings: list[str] = []
    question = str(args.get("question") or "").strip()[:_Q_LIMIT]
    options = _clean_options(args.get("options"))
    kwargs: dict[str, Any] = {}

    # Anonymity — default False ("Show Who Voted" is ON in the Telegram UI).
    anon = _opt_bool(args, "is_anonymous")
    kwargs["is_anonymous"] = False if anon is None else anon

    # Quiz handling: needs valid correct index(es); else degrade to a regular poll.
    is_quiz = args.get("type") == "quiz"
    if is_quiz:
        ids = args.get("correct_option_ids")
        if not ids and isinstance(args.get("correct_option_id"), int):
            ids = [args["correct_option_id"]]
        ids = sorted({i for i in (ids or []) if isinstance(i, int) and 0 <= i < len(options)})
        if not ids:
            warnings.append("quiz had no valid correct answer — sent as a regular poll")
            is_quiz = False
        else:
            kwargs["type"] = "quiz"
            # The Bot API allows exactly one correct answer (QUIZ_CORRECT_
            # ANSWERS_TOO_MUCH otherwise) — the UI's "one or more" is client-only.
            kwargs["correct_option_id"] = ids[0]
            if len(ids) > 1:
                warnings.append("Telegram quizzes allow only one correct answer — used the first")
            expl = str(args.get("explanation") or "").strip()
            if expl:
                kwargs["explanation"] = expl[:_EXPL_LIMIT]

    # Multiple answers — quizzes can't have them.
    multi = _opt_bool(args, "allows_multiple_answers")
    if is_quiz:
        if multi:
            warnings.append("quizzes can't allow multiple answers — ignored")
    elif multi:
        kwargs["allows_multiple_answers"] = True

    # Revoting — incompatible with quizzes and multi-answer polls.
    revote = _opt_bool(args, "allows_revoting")
    if revote and not is_quiz and not kwargs.get("allows_multiple_answers"):
        kwargs["allows_revoting"] = True

    # Remaining toggles — forward only when explicitly requested (True).
    if _opt_bool(args, "allow_adding_options") and not is_quiz:
        kwargs["allow_adding_options"] = True
    if _opt_bool(args, "shuffle_options"):
        kwargs["shuffle_options"] = True
    if _opt_bool(args, "hide_results_until_closes"):
        kwargs["hide_results_until_closes"] = True

    desc = str(args.get("description") or "").strip()
    if desc:
        kwargs["description"] = desc[:_DESC_LIMIT]

    # Auto-close — Bot API open_period is 5..600 seconds.
    secs = args.get("auto_close_seconds")
    if isinstance(secs, (int, float)) and secs >= 1:
        s = int(secs)
        if s > _MAX_PERIOD:
            warnings.append(f"auto-close capped at {_MAX_PERIOD}s (Bot API limit)")
            s = _MAX_PERIOD
        kwargs["open_period"] = max(_MIN_PERIOD, s)

    return question, options, kwargs, warnings


async def create_poll_in_chat(
    bot: Bot, chat_id: int, db: Database, args: dict
) -> str:
    """Build, validate, send and record a poll. Returns a user-facing summary."""
    question, options, kwargs, warnings = build_poll_kwargs(args)
    if not question:
        return "⚠️ I couldn't work out the poll question — please rephrase."
    if len(options) < _MIN_OPTIONS:
        return "⚠️ A poll needs at least two options. Add a few and try again."

    sent = await bot.send_poll(
        chat_id=chat_id,
        question=question,
        options=[InputPollOption(text=o) for o in options],
        **kwargs,
    )
    poll_id = sent.poll.id if sent.poll else ""
    await db.record_poll(chat_id, sent.message_id, poll_id, question)

    kind = "Quiz" if kwargs.get("type") == "quiz" else "Poll"
    extras = _describe_settings(kwargs)
    line = f"📊 {kind} created — {len(options)} options"
    if extras:
        line += f" ({', '.join(extras)})"
    line += "."
    if warnings:
        line += "\n⚠️ " + "; ".join(warnings)
    return line


def _describe_settings(kwargs: dict) -> list[str]:
    """Human-readable list of the non-default settings actually applied."""
    out: list[str] = []
    out.append("anonymous" if kwargs.get("is_anonymous") else "shows voters")
    if kwargs.get("allows_multiple_answers"):
        out.append("multiple answers")
    if kwargs.get("allows_revoting"):
        out.append("revoting")
    if kwargs.get("allow_adding_options"):
        out.append("adding options")
    if kwargs.get("shuffle_options"):
        out.append("shuffled")
    if kwargs.get("hide_results_until_closes"):
        out.append("hidden results")
    if kwargs.get("description"):
        out.append("description")
    if kwargs.get("open_period"):
        out.append(f"auto-close {kwargs['open_period']}s")
    return out


async def _do_create(message: Message, bot: Bot, db: Database, args: dict) -> str:
    return await create_poll_in_chat(bot, message.chat.id, db, args)


async def _do_close(message: Message, bot: Bot, db: Database) -> str:
    last = await db.get_last_open_poll(message.chat.id)
    if last is None:
        return "There's no open poll in this chat to close."
    mid, _poll_id = last
    try:
        await bot.stop_poll(chat_id=message.chat.id, message_id=mid)
    except Exception as exc:  # noqa: BLE001 — poll may be gone / already closed
        await db.mark_poll_closed(message.chat.id, mid)
        return f"⚠️ Couldn't close the poll (it may already be closed): {exc}"
    await db.mark_poll_closed(message.chat.id, mid)
    return "🛑 Poll closed."


async def maybe_handle_poll(
    message: Message,
    text: str,
    *,
    bot: Bot,
    db: Database,
    llama: LlamaClient,
    model: str,
    images: list[ImagePart] | None = None,
    history: list[dict] | None = None,
) -> str | None:
    """Try to handle ``text`` as a poll command.

    ``images`` (a menu/flyer attached to the message or the one it replies to)
    and ``history`` (recent text turns) are passed to the tool model so it can
    EXTRACT poll options from a picture or earlier context instead of asking the
    user to resend it.

    Returns a confirmation string when a poll tool was invoked (the message is
    fully handled), or ``None`` to signal the caller should fall through to the
    normal chat answer. Never raises — failures are returned as user-facing text.
    """
    if not looks_poll_related(text):
        return None
    messages: list[dict] = [{"role": "system", "content": _SYSTEM}]
    if history:
        messages.extend(history)
    messages.append(user_message(text, images))
    try:
        msg = await llama.tool_call(model, messages, TOOLS, max_tokens=500)
    except LlamaError as exc:
        log.warning("poll tool call failed: %s", exc)
        return None  # fall through to a normal answer rather than block the user

    calls = parse_tool_calls(msg)
    if not calls:
        return None  # model decided it isn't a poll request

    name, args = calls[0]
    try:
        if name == "create_poll":
            return await _do_create(message, bot, db, args)
        if name == "close_poll":
            return await _do_close(message, bot, db)
    except Exception as exc:  # noqa: BLE001 — surface, never crash the handler
        log.exception("poll execution error")
        return f"⚠️ Sorry, I couldn't do that with the poll: {exc}"
    return None
