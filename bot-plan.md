# Telegram Assistant Bot — Implementation Plan & Progress

A personal Telegram assistant, summonable **anywhere** (any group/DM) via Telegram's
new **Guest Mode**, backed by the local Open WebUI API. Answers **only for the admin**.

## Decisions
- **Backend:** Open WebUI API (`http://open-webui:8080`) — web search + 2 model entries.
- **Reach:** Guest Mode (`@mention` anywhere) + Direct DM. (No Business mode.)
- **Models:** fast by default; `/think` keyword overrides per-message; `/mode` sets default.
- **Memory:** per-chat history in SQLite for DMs; guest mode stays stateless.
- **Transport:** long polling (no webhook). `allowed_updates` includes `message`, `guest_message`.

## Confirmed API facts
- aiogram **3.28.2** — Bot API 10.0: `Update.guest_message`, `guest_message` observer,
  `Message.guest_query_id` / `guest_bot_caller_user` / `guest_bot_caller_chat`, `AnswerGuestQuery`.
- Open WebUI: `POST /api/chat/completions`, `GET /api/models`, RAG `POST /api/v1/files/`;
  auth `Authorization: Bearer <key>` (Settings → Account).

## Layout
```
bot/
  main.py        config.py      openwebui.py   db.py
  routing.py     formatting.py  Dockerfile
  handlers/  dm.py  guest.py  commands.py
requirements.txt
```

## Progress

### Phase 1 — Core  ✅ implemented
- [x] `requirements.txt` + `bot/Dockerfile`
- [x] `bot/config.py` — env loading
- [x] `bot/openwebui.py` — async client: stream_chat, list_models, upload_file
- [x] `bot/db.py` — aiosqlite: per-chat history + mode + web-search setting
- [x] `bot/routing.py` — `/think` / `/fast` flag parsing, model selection
- [x] `bot/formatting.py` — strip `<think>`, split >4096 chars
- [x] `bot/prompts.py` — shared system prompt (date-stamped)
- [x] `bot/middleware.py` — admin-only gate on message + guest_message
- [x] `bot/handlers/commands.py` — /start /help /mode /web /reset /new /status
- [x] `bot/handlers/dm.py` — DM Q&A, streaming edits, history + web search
- [x] `bot/handlers/guest.py` — guest_message → one answerGuestQuery reply
- [x] `bot/main.py` — dispatcher, polling, allowed_updates, startup model check
- [x] `docker-compose.yml` — add `bot` service + `bot-data` volume
- [x] `.env` — add bot variables
- [x] `README.md` — bot setup instructions

> Note: `/think` and `/fast` are inline message flags (handled in `routing.py`),
> not slash commands — `/mode` sets the persistent default. This avoids the
> ambiguity of `/think` being both a command and an inline flag.

### Phase 2 — Per-message tools  ✅ implemented
- [x] `bot/tasks.py` — task prompt templates
- [x] `bot/engine.py` — shared streaming-reply helper (reused by dm + tools)
- [x] Summarize message / text / URL — `/summarize`
- [x] Translate — `/translate <language>`
- [x] Rewrite / tone fixer — `/rewrite <style>`

### Phase 3 — DM-only  ✅ implemented
- [x] Chat-with-PDF (RAG): upload via `/api/v1/files/`, poll status, attach `file_ids`
- [x] `chat_files` table + `/files` command (list / clear)

### Phase 4 — Speech-to-text  ✅ implemented
- [x] `transcribe_audio()` — Open WebUI `POST /api/v1/audio/transcriptions`
- [x] Voice / audio handler in `dm.py`: transcribe, show transcript, then answer it

## One-time manual setup
1. Create bot via `@BotFather`, copy token → `.env`.
2. BotFather MiniApp → Bot Settings → enable **Guest Mode**.
3. Open WebUI: create the two model entries (thinking/fast), enable web search, generate API key.
4. Get numeric Telegram user id (`@userinfobot`) → `.env` `ADMIN_USER_ID`.

## Verification
- `docker compose up -d`; bot log shows both model ids found.
- DM: current-events question → web-search answer; follow-up → memory; `/reset` clears.
- `/think` keyword → thinking model; `/mode think` → default switches.
- Guest: `@mention` from admin → reply; from non-admin → silence.
- `docker compose stop llama` → clean "model unavailable" message.
