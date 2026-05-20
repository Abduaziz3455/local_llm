# Local Qwen + Open WebUI

A local AI stack in two files: **llama.cpp** (runs your GGUF model) + **Open WebUI**
(chat dashboard with web search, document upload/RAG, and thinking mode). Everything
runs on your machine — no API keys, works offline after the first image pull.

## Files

```
docker-compose.yml   # the stack
.env                 # all settings: ports, model, cache path
README.md            # this file
```

Put all three in the same folder.

---

## Requirements

1. **Docker** with the Compose plugin (`docker compose version` should work).
2. **A downloaded GGUF model** in your HuggingFace cache (you already have one).
   To get another later:
   ```bash
   pip install -U huggingface_hub
   hf download unsloth/Qwen3.5-9B-GGUF --include "*UD-Q4_K_XL*"
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
| `MODEL_REPO` | `models--unsloth--Qwen3.5-9B-GGUF`       | Which model folder to load                     |
| `QUANT`      | *(blank)*                                | Pin a quant if a repo has several, e.g. `UD-Q4_K_XL` |
| `HF_HUB`     | `/home/abduaziz/.cache/huggingface/hub`  | Your HuggingFace cache location                |

Change a value, then `docker compose up -d`.

### Switching models

Point `MODEL_REPO` at any model folder you've downloaded:

```bash
# edit .env, or override for one run:
MODEL_REPO=models--unsloth--Qwen3.6-27B-GGUF docker compose up -d
```

> Note: the sampling defaults in the compose file are tuned for **Qwen3.5**. A
> same-family model just works; a different family may want different sampling.

---

## Thinking mode (on/off)

Thinking is **not forced** by the server — you control it in the dashboard. Qwen3.5
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

> Tip: if the 9B gets stuck in long thinking loops, prefer the "fast" entry, or lower
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
You're on CPU. Expected for a 9B — use the GPU path, or a smaller quant/model.

**Garbled output, or endless "thinking" loops (9B)**
Lower `--temp` to `0.6` in the compose file. For garbled text, the context may be
too low (raise `-c`) or it's a KV-cache issue (add `--cache-type-k bf16 --cache-type-v bf16`).

**Web search returns nothing**
DuckDuckGo (the keyless default) can rate-limit. Switch the engine in
Admin Panel → Settings → Web Search, or set a keyed provider like Tavily.

---

## Stop / reset

```bash
docker compose down              # stop
docker compose down -v           # stop + delete chats/settings (the open-webui volume)
docker compose pull && docker compose up -d   # update to latest images
```
