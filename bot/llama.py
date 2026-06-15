"""Minimal direct client for the llama-swap OpenAI-compatible endpoint.

The Telegram bot normally talks to Open WebUI (for web search, RAG, history),
but Open WebUI does not cleanly forward OpenAI ``tools``/``tool_calls`` to the
upstream model. For *tool calling* (the poll feature) we therefore bypass it and
talk straight to llama-swap (`llama:8080/v1`) over the internal Docker network,
which returns native ``tool_calls`` reliably (proven by tooltest/).

This client is tiny on purpose: one non-streaming chat call that returns the
raw assistant message dict (with ``tool_calls`` or ``content``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class LlamaError(RuntimeError):
    """Raised when the llama-swap endpoint is unreachable or errors."""


class LlamaClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def tool_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 300,
    ) -> dict[str, Any]:
        """One non-streaming completion with tools enabled.

        Returns the assistant message dict — inspect ``["tool_calls"]`` (a list
        when the model decided to call a function) or ``["content"]`` (plain
        text when it did not). Raises ``LlamaError`` on transport/HTTP failure.
        """
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            if resp.status_code >= 400:
                raise LlamaError(f"llama returned {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
        except httpx.HTTPError as exc:
            raise LlamaError(f"llama request failed: {exc}") from exc
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LlamaError(f"unexpected llama response: {str(data)[:300]}") from exc


def parse_tool_calls(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Extract ``[(function_name, args_dict), ...]`` from an assistant message.

    Returns an empty list when no tool was called. Malformed JSON arguments
    yield ``{}`` for that call rather than raising.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        if not name:
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        out.append((name, args))
    return out
