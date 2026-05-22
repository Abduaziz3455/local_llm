"""Async client for the Open WebUI API.

Open WebUI exposes an OpenAI-shaped surface at ``/api``:
  * ``GET  /api/models``            — list available model entries
  * ``POST /api/chat/completions``  — chat (supports ``stream: true``)
  * ``POST /api/v1/files/``         — upload a file for RAG (phase 3)

Auth is a bearer token generated in Open WebUI → Settings → Account.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterable

import httpx


class OpenWebUIError(RuntimeError):
    """Raised when the Open WebUI API is unreachable or returns an error."""


# ``content`` is usually a plain string, but for multimodal turns it becomes a
# list of OpenAI-shaped content parts (text + image_url) — hence the ``Any``.
Message = dict[str, Any]


class OpenWebUIClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 180.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        """Return the ids of every model entry Open WebUI knows about."""
        try:
            resp = await self._client.get("/api/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenWebUIError(f"Could not reach Open WebUI: {exc}") from exc
        data = resp.json().get("data", [])
        return [m.get("id", "") for m in data if m.get("id")]

    async def stream_chat(
        self,
        model: str,
        messages: Iterable[Message],
        *,
        web_search: bool = False,
        file_ids: Iterable[str] | None = None,
        chat_id: str = "local:telegram",
        stats: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text deltas as they arrive.

        ``web_search`` toggles Open WebUI's search tool for this request;
        ``file_ids`` attaches previously uploaded files for RAG.

        If ``stats`` is given, the final chunk's ``finish_reason`` is written
        to ``stats["finish_reason"]`` — callers use this to tell a complete
        answer apart from one the model cut short (``"length"``).

        ``chat_id`` must be sent: Open WebUI's payload processing calls
        ``metadata['chat_id'].startswith(...)`` unconditionally, so a missing
        id becomes ``None`` and 400s the request. The ``local:`` prefix marks
        a temporary chat Open WebUI won't persist — the bot keeps its own
        history — and satisfies those guards.
        """
        payload: dict = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "chat_id": chat_id,
        }
        if web_search:
            payload["features"] = {"web_search": True}
        if file_ids:
            payload["files"] = [{"type": "file", "id": fid} for fid in file_ids]

        try:
            async with self._client.stream(
                "POST", "/api/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise OpenWebUIError(
                        f"Open WebUI returned {resp.status_code}: {body[:300]}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    if stats is not None and choices[0].get("finish_reason"):
                        stats["finish_reason"] = choices[0]["finish_reason"]
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:
            raise OpenWebUIError(f"Open WebUI request failed: {exc}") from exc

    async def complete_chat(
        self,
        model: str,
        messages: Iterable[Message],
        *,
        web_search: bool = False,
        file_ids: Iterable[str] | None = None,
        chat_id: str = "local:telegram",
    ) -> str:
        """Non-streaming convenience wrapper — accumulates the full reply."""
        parts: list[str] = []
        async for delta in self.stream_chat(
            model, messages, web_search=web_search, file_ids=file_ids, chat_id=chat_id
        ):
            parts.append(delta)
        return "".join(parts)

    async def upload_file(self, filename: str, content: bytes) -> str:
        """Upload a file for RAG; returns its file id (phase 3)."""
        try:
            resp = await self._client.post(
                "/api/v1/files/",
                files={"file": (filename, content)},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenWebUIError(f"File upload failed: {exc}") from exc
        return resp.json()["id"]

    async def transcribe_audio(
        self, filename: str, content: bytes, content_type: str = "audio/ogg"
    ) -> str:
        """Speech-to-text via Open WebUI's STT engine; returns the transcript."""
        try:
            resp = await self._client.post(
                "/api/v1/audio/transcriptions",
                files={"file": (filename, content, content_type)},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenWebUIError(f"Transcription failed: {exc}") from exc
        return (resp.json().get("text") or "").strip()

    async def file_process_status(self, file_id: str) -> str:
        """Return the processing status for an uploaded file (phase 3)."""
        try:
            resp = await self._client.get(f"/api/v1/files/{file_id}/process/status")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenWebUIError(f"Could not read file status: {exc}") from exc
        return resp.json().get("status", "unknown")
