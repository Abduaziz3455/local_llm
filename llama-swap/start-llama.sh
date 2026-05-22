#!/bin/sh
# =============================================================================
#  Launcher for llama-server, invoked by llama-swap.
# -----------------------------------------------------------------------------
#  llama-swap calls this on the FIRST request after the model is idle-unloaded,
#  passing the dynamically-assigned upstream port as $1 (the ${PORT} macro).
#
#  Same model-discovery logic as the old docker-compose entrypoint: find the
#  GGUF (and optional vision "mmproj" file) for $MODEL_REPO in the mounted
#  HuggingFace cache, or fall back to downloading $HF_MODEL.
#
#  Reads these env vars (passed through from .env by docker-compose):
#    MODEL_REPO, QUANT, N_CPU_MOE, HF_MODEL, HF_TOKEN, LLAMA_CACHE
# =============================================================================
set -e

PORT="$1"
if [ -z "$PORT" ]; then
  echo "start-llama.sh: no port given (llama-swap passes \${PORT} as \$1)" >&2
  exit 1
fi

REPO="${MODEL_REPO:-models--unsloth--Qwen3.6-35B-A3B-GGUF}"
MODEL=$(find "/hub/$REPO" -iname "*${QUANT:-}*.gguf" 2>/dev/null | grep -vi mmproj | sort | head -n1)
MMPROJ=$(find "/hub/$REPO" -iname "*mmproj*.gguf" 2>/dev/null | sort | head -n1)

if [ -n "$MODEL" ]; then
  echo "==> Loading local model: $MODEL"
  set -- -m "$MODEL"
  if [ -n "$MMPROJ" ]; then
    echo "==> Vision projector: $MMPROJ"
    set -- "$@" --mmproj "$MMPROJ"
  else
    echo "==> No mmproj file found under /hub/$REPO — image input disabled."
  fi
elif [ -n "${HF_MODEL:-}" ]; then
  echo "==> Not found under /hub/$REPO; downloading from HuggingFace: $HF_MODEL"
  set -- -hf "$HF_MODEL"
  # llama.cpp's -hf auto-downloads the repo's mmproj when one exists.
else
  echo "No .gguf found under /hub/$REPO and HF_MODEL is not set" >&2
  exit 1
fi

# --host 127.0.0.1: only llama-swap (same container) talks to this server.
exec llama-server \
  "$@" \
  --host 127.0.0.1 --port "$PORT" \
  --alias local-llm \
  --api-key local \
  -c 16384 \
  -ngl 99 \
  --n-cpu-moe "${N_CPU_MOE:-99}" \
  -fa on \
  --jinja \
  --chat-template-kwargs '{"enable_thinking":false}' \
  --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 --presence-penalty 1.5
# Sampling / MoE-offload notes: see comments in .env and the README. Tune
# N_CPU_MOE in .env; add --no-mmproj-offload above if the vision encoder OOMs.
