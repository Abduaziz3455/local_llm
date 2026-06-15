#!/bin/sh
# =============================================================================
#  Launcher for llama-server, invoked by llama-swap.
# -----------------------------------------------------------------------------
#  llama-swap calls this on the FIRST request after a model is idle-unloaded,
#  passing the dynamically-assigned upstream port as $1 (the ${PORT} macro) and
#  a PROFILE name as $2 (which model to launch). One profile = one model entry
#  in config.yaml, so llama-swap can swap between them by requested model id.
#
#    $1  upstream port (from llama-swap ${PORT})
#    $2  profile: "qwen" (default) or "gemma"
#
#  Each profile selects a HuggingFace-cache repo + quant and the model-specific
#  llama-server flags (sampling, MoE offload, MTP draft, vision projector).
#
#  Reads these env vars (passed through from .env by docker-compose):
#    MODEL_REPO, QUANT, N_CPU_MOE, HF_MODEL, HF_TOKEN, LLAMA_CACHE
# =============================================================================
set -e

PORT="$1"
PROFILE="${2:-qwen}"
if [ -z "$PORT" ]; then
  echo "start-llama.sh: no port given (llama-swap passes \${PORT} as \$1)" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
#  Per-profile model selection. The qwen profile keeps the original behaviour
#  (driven by .env MODEL_REPO/QUANT); the gemma profile hard-codes the
#  gemma-4-12b repo and its MTP drafter.
# -----------------------------------------------------------------------------
case "$PROFILE" in
  gemma)
    REPO="models--unsloth--gemma-4-12b-it-GGUF"
    QUANT="UD-Q4_K_XL"
    HF_FALLBACK="unsloth/gemma-4-12b-it-GGUF:UD-Q4_K_XL"
    ;;
  qwen|*)
    REPO="${MODEL_REPO:-models--unsloth--Qwen3.6-35B-A3B-GGUF}"
    QUANT="${QUANT:-}"
    HF_FALLBACK="${HF_MODEL:-}"
    ;;
esac

# Find the main weights (skip mmproj vision files and MTP drafter files).
MODEL=$(find "/hub/$REPO" -iname "*${QUANT:-}*.gguf" 2>/dev/null \
          | grep -vi mmproj | grep -vi mtp | sort | head -n1)
MMPROJ=$(find "/hub/$REPO" -iname "*mmproj*.gguf" 2>/dev/null | sort | head -n1)

if [ -n "$MODEL" ]; then
  echo "==> [$PROFILE] Loading local model: $MODEL"
  set -- -m "$MODEL"
  if [ -n "$MMPROJ" ]; then
    echo "==> Vision projector: $MMPROJ"
    set -- "$@" --mmproj "$MMPROJ"
  else
    echo "==> No mmproj file found under /hub/$REPO — image input disabled."
  fi
elif [ -n "$HF_FALLBACK" ]; then
  echo "==> [$PROFILE] Not found under /hub/$REPO; downloading from HuggingFace: $HF_FALLBACK"
  set -- -hf "$HF_FALLBACK"
  # llama.cpp's -hf auto-downloads the repo's mmproj when one exists.
else
  echo "No .gguf found under /hub/$REPO and no HF fallback set" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
#  Per-profile llama-server flags.
# -----------------------------------------------------------------------------
case "$PROFILE" in
  gemma)
    # Gemma-4-12b is a DENSE model (no MoE) -> no --n-cpu-moe; fits a 12 GB GPU.
    #
    # MTP (Multi-Token Prediction): a small drafter head shipped inside the repo
    # under MTP/ proposes several tokens per step that the main model verifies
    # (~1.4-2.2x faster, lossless). With local files the drafter is NOT
    # auto-discovered, so we find it and pass it via --model-draft.
    # Prefer the small Q8_0 drafter (~0.4 GB) over BF16/F16 (~0.8 GB) to save VRAM.
    MTP_DRAFT=$(find "/hub/$REPO" -ipath "*mtp*" -iname "*Q8_0*.gguf" 2>/dev/null | head -n1)
    [ -z "$MTP_DRAFT" ] && MTP_DRAFT=$(find "/hub/$REPO" -ipath "*mtp*" -iname "*.gguf" 2>/dev/null \
                  | sort | head -n1)
    if [ -n "$MTP_DRAFT" ]; then
      echo "==> MTP drafter: $MTP_DRAFT (--spec-type draft-mtp)"
      set -- "$@" --model-draft "$MTP_DRAFT" --spec-type draft-mtp --spec-draft-n-max 2
    else
      echo "==> No MTP drafter found under /hub/$REPO/MTP — running WITHOUT MTP."
    fi
    # Google's recommended Gemma sampling: temp 1.0, top-p 0.95, top-k 64.
    exec llama-server \
      "$@" \
      --host 127.0.0.1 --port "$PORT" \
      --alias gemma-4-12b \
      --api-key local \
      -c 16384 \
      -ngl 99 \
      -fa on \
      --jinja \
      --chat-template-kwargs '{"enable_thinking":false}' \
      --temp 1.0 --top-p 0.95 --top-k 64
    ;;
  qwen|*)
    # Original Qwen3.6-35B-A3B (MoE) behaviour — experts offloaded to CPU RAM.
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
    ;;
esac
# Sampling / MoE-offload notes: see comments in .env and the README. Tune
# N_CPU_MOE in .env; add --no-mmproj-offload above if the vision encoder OOMs.
# If gemma OOMs on 12 GB: lower -c, or drop --mmproj (remove that line above).
