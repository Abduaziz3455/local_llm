"""
Tool (function) schemas for the poll creator/editor — shared by the test
harness. These are OpenAI-style `tools` definitions sent to llama.cpp's
`/v1/chat/completions` (with `--jinja` enabling the chat template's tool
grammar). Mirrors what a real Telegram poll bot would expose
(Bot API sendPoll / stopPoll fields).
"""

CREATE_POLL = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            "Create a new poll/survey in the chat. Use this whenever the user "
            "asks to make, start, or set up a poll, survey, vote, or quiz. "
            "Works for any language (English, Uzbek, Russian, ...)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The poll question shown to participants.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The answer options (2-10 items).",
                },
                "is_anonymous": {
                    "type": "boolean",
                    "description": "True if votes should be anonymous. Default true.",
                },
                "allows_multiple_answers": {
                    "type": "boolean",
                    "description": "True if a voter may pick several options. Default false.",
                },
                "type": {
                    "type": "string",
                    "enum": ["regular", "quiz"],
                    "description": "'quiz' if there is one correct answer, else 'regular'.",
                },
                "correct_option_id": {
                    "type": "integer",
                    "description": "0-based index of the correct option (quiz polls only).",
                },
            },
            "required": ["question", "options"],
        },
    },
}

EDIT_POLL = {
    "type": "function",
    "function": {
        "name": "edit_poll",
        "description": (
            "Edit or stop an existing poll: change its question, add/remove "
            "options, or close it. Use only when the user refers to an already "
            "created poll."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "poll_id": {
                    "type": "string",
                    "description": "Identifier of the poll to edit. Use 'last' if unspecified.",
                },
                "action": {
                    "type": "string",
                    "enum": ["change_question", "add_option", "remove_option", "close"],
                    "description": "What to change.",
                },
                "value": {
                    "type": "string",
                    "description": "New question text or the option to add/remove (if any).",
                },
            },
            "required": ["action"],
        },
    },
}

TOOLS = [CREATE_POLL, EDIT_POLL]
