# Local Qwen + Open WebUI

A local AI stack in two files: **llama.cpp** (runs your GGUF model) + **Open WebUI**
(chat dashboard with web search, document upload/RAG, and thinking mode). Everything
runs on your machine — no API keys, works offline after the first image pull.

## Files

```
docker-compose.yml   # the stack (llama.cpp + Open WebUI + Telegram bot)
.env                 # all settings: ports, model, cache path, bot config
README.md            # this file
requirements.txt     # Python deps for the Telegram bot
bot/                 # Telegram assistant bot source
```

Keep `docker-compose.yml`, `.env` and `README.md` in the same folder.

---

## Requirements

1. **Docker** with the Compose plugin (`docker compose version` should work).
2. **A downloaded GGUF model** in your HuggingFace cache (you already have one).
   To get another later:
   ```bash
   pip install -U huggingface_hub
   hf download unsloth/Qwen3.6-35B-A3B-GGUF --include "*UD-Q4_K_XL*"
   ```
3. **For GPU only:** an NVIDIA driver (`nvidia-smi` works on the host) **and** the
   NVIDIA Container Toolkit (see below). **CPU works with no extra setup.**

---

## Setup & Run

### Option A — NVIDIA GPU (fast)

Install the NVIDIA Container Toolkit once (this is what fixes the
`could not select device driver "nvidia"` error):

```bash
# Add NVIDIA's repo
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install + register the runtime with Docker
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify GPU passthrough works:

```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
```

If you see the GPU table, you're good. Then:

```bash
docker compose up -d
```

### Option B — CPU only (no GPU needed)

Make **2 edits** in `docker-compose.yml` (both marked `[CPU]`):

1. Change the image tag:
   `ghcr.io/ggml-org/llama.cpp:server-cuda` → `ghcr.io/ggml-org/llama.cpp:server`
2. Delete the entire `deploy:` block (the `resources / reservations / devices` lines).

Then:

```bash
docker compose up -d
```

> First run downloads the two images and loads the model (~30–60s). After that it's instant.

---

## Using it

- **Dashboard:** http://localhost:3000  (web search, document upload, thinking)
- **Raw API:** http://localhost:8080/v1  (OpenAI-compatible — for bots/scripts)

The model appears automatically as `local-llm`. No login, no setup clicks.

---

## Configuration (`.env`)

| Variable     | Default                                  | What it does                                   |
|--------------|------------------------------------------|------------------------------------------------|
| `WEBUI_PORT` | `3000`                                   | Dashboard port on your machine                 |
| `LLAMA_PORT` | `8080`                                   | API port on your machine                       |
| `MODEL_REPO` | `models--unsloth--Qwen3.6-35B-A3B-GGUF`  | Which model folder to load                     |
| `QUANT`      | `UD-Q4_K_XL`                             | Pin a quant if a repo has several              |
| `N_CPU_MOE`  | `99`                                     | MoE expert layers offloaded to RAM; lower = faster, more VRAM |
| `HF_HUB`     | `/home/abduaziz/.cache/huggingface/hub`  | Your HuggingFace cache location                |

Change a value, then `docker compose up -d`.

### Switching models

Point `MODEL_REPO` at any model folder you've downloaded:

```bash
# edit .env, or override for one run:
MODEL_REPO=models--unsloth--Qwen3.6-27B-GGUF docker compose up -d
```

> Note: the sampling defaults in the compose file are tuned for **Qwen3.6**. A
> same-family model just works; a different family may want different sampling.
> A **dense** model (e.g. Qwen3.6-27B) ignores `N_CPU_MOE` — for those, drop
> `-ngl` instead to offload whole layers if it doesn't fit in VRAM.

---

## Thinking mode (on/off)

Thinking is **not forced** by the server — you control it in the dashboard. Qwen3.6
defaults to thinking **off**. There's no one-click button (Open WebUI's native think
toggle is Ollama-only), so the clean way is to make two model entries and switch with
the model dropdown:

1. Go to **Workspace → Models → + Add Model** (or edit `local-llm`).
2. Base model: `local-llm`. Name it e.g. **Qwen (thinking)**.
3. In **Advanced Params**, add a custom parameter:
   - key: `chat_template_kwargs`  value: `{"enable_thinking": true}`
   - (optional) `temperature` `1.0`, `top_p` `0.95`
4. Save. Make a second entry **Qwen (fast)** with `{"enable_thinking": false}`
   and `temperature` `0.7`, `top_p` `0.8`.

Now the model picker at the top of the chat is your on/off switch. When thinking is on,
Open WebUI shows the reasoning in a collapsible block automatically.

> Tip: if the model gets stuck in long thinking loops, prefer the "fast" entry, or lower
> its temperature.

---

## Common errors

**`could not select device driver "nvidia" with capabilities: [[gpu]]`**
The NVIDIA Container Toolkit isn't installed/registered. Do Option A above, or
switch to CPU (Option B). Confirm the driver first with `nvidia-smi` on the host.

**`bind: address already in use` / port conflict**
Something else uses 3000 or 8080. Change `WEBUI_PORT` / `LLAMA_PORT` in `.env`.

**`No .gguf found under /hub/...`**
`MODEL_REPO` or `HF_HUB` is wrong. Check the folder name:
`ls ~/.cache/huggingface/hub`.

**Model is very slow**
On CPU this is expected — use the GPU path. On GPU, the experts are RAM-resident:
lower `N_CPU_MOE` in `.env` to push more onto the GPU (watch `nvidia-smi` for OOM).

**Garbled output, or endless "thinking" loops**
Lower `--temp` to `0.6` in the compose file. For garbled text, the context may be
too low (raise `-c`) or it's a KV-cache issue (add `--cache-type-k bf16 --cache-type-v bf16`).

**Web search returns nothing**
DuckDuckGo (the keyless default) can rate-limit. Switch the engine in
Admin Panel → Settings → Web Search, or set a keyed provider like Tavily.

---

## Telegram assistant bot

A personal Telegram assistant backed by this local stack. It runs as the `bot`
service in the compose file and answers **only you** — anywhere on Telegram.

**Two ways to reach it:**
- **Direct DM** — a normal 1-1 chat with the bot. Keeps conversation memory, has
  commands, uses web search.
- **Guest Mode** — `@mention` the bot's username in *any* group or chat and it
  replies once, even though it isn't a member. Guest replies are stateless: one
  question, one answer, no memory (a Telegram limitation, not a bug).

### One-time setup

1. **Create the bot.** Message [@BotFather](https://t.me/BotFather) → `/newbot`,
   copy the token into `TELEGRAM_BOT_TOKEN` in `.env`.
2. **Enable Guest Mode.** In BotFather, open the bot's settings MiniApp and turn
   on **Guest Mode** (so `@mention` works in any chat).
3. **Find your user id.** Message [@userinfobot](https://t.me/userinfobot), copy
   the number into `ADMIN_USER_IDS`. Comma-separate several ids to allow more
   than one admin. The bot ignores everyone else.
4. **Create the two model entries** in Open WebUI → **Workspace → Models**
   (see *Thinking mode* above). Name them so their ids match `MODEL_FAST` and
   `MODEL_THINKING` in `.env` (default `qwen-fast` / `qwen-thinking`). Enable web
   search on them, or the bot still works without it.
5. **Generate an API key.** Open WebUI → **Settings → Account → API keys** →
   create one, copy it into `OPENWEBUI_API_KEY`.

### Run

```bash
docker compose up -d           # starts llama + open-webui + bot
docker compose logs -f bot     # watch the bot; it logs which models it found
```

DM the bot `/start` to confirm it's alive.

### Using it

- **Ask anything** in DM — it answers with web search and remembers the chat.
- **Model flag:** add `/think` (or `!t`) anywhere in a message for the slower
  reasoning model; `/fast` (`!f`) forces the quick one. Put the flag at the end.
- **Tools** — reply to a message with one of these, or pass text inline:
  `/summarize` (text or URL), `/translate <language>`, `/rewrite <style>`.
- **Chat with a document** — send a PDF/text file to the bot; once it says the
  file is ready, ask questions about it. `/files` lists them, `/files clear`
  removes them.
- **Voice messages** — send a voice message or audio file; the bot transcribes
  it with Open WebUI's speech-to-text and answers it as a question.
- **Images** — send a photo (or an image as a file); the multimodal model reads
  it. Add a caption to ask a specific question, or send it bare for a
  description. You can also **reply** to an earlier photo with a follow-up
  question, and mentioning the bot on a photo works in guest mode too.
- **Stop a reply** — `/stop` cancels the answer that's currently streaming;
  sending a new question also supersedes the one in progress. Every generation
  is capped at `RESPONSE_TIMEOUT` seconds (default 120) so it can't run away.
- **Commands:** `/mode think|fast` (default model), `/web on|off` (web search),
  `/files` (attached docs), `/stop` (cancel current reply), `/reset` (forget
  history), `/status` (backend health), `/help`.
- **Guest mode:** in any chat, type `@yourbotname <question>` → one reply.

### Bot errors

**Bot replies "model unavailable"** — Open WebUI or `llama` is down, or the model
is still loading. Check `docker compose logs -f open-webui llama`.

**`/status` shows "not found" for a model** — the `MODEL_FAST` / `MODEL_THINKING`
ids in `.env` don't match the model-entry ids in Open WebUI. Fix the names.

**Guest `@mention` does nothing** — Guest Mode isn't enabled in BotFather, or you
mentioned it from a non-admin account (the bot stays silent for everyone else).

**Voice transcription fails** — Open WebUI's speech-to-text engine isn't ready.
Check Admin Panel → Settings → Audio (the local Whisper engine works out of the
box; the first transcription downloads its model).

**`Missing required environment variable`** — fill in `TELEGRAM_BOT_TOKEN`,
`ADMIN_USER_IDS` and `OPENWEBUI_API_KEY` in `.env`, then `docker compose up -d`.

---

## Stop / reset

```bash
docker compose down              # stop
docker compose down -v           # stop + delete all data (open-webui + bot history volumes)
docker compose pull && docker compose up -d   # update to latest images
```
