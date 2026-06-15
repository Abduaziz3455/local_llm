# Poll tool-calling evaluation — Gemma-4-12b vs Qwen3.5-2B

Goal: decide between two bot architectures for a **poll creator/editor** feature.

- **Config A** — Gemma-4-12b does tool-calling **and** general Q&A.
- **Config B** — Qwen3.5-2B (Q8_0) does tool-calling, Gemma-4-12b answers general questions.

The only thing that differs between A and B is the *tool-caller*, so the harness
runs the same suite against each model as the tool-caller and compares. General
answers are Gemma's in both configs.

## Setup
- Served via the existing Docker `llama-swap` stack on `http://localhost:5002/v1`
  (api-key `local`). Added a `qwen2b` profile in
  [llama-swap/start-llama.sh](../llama-swap/start-llama.sh) and the `qwen3.5-2b`
  model entry in [llama-swap/config.yaml](../llama-swap/config.yaml).
- Model: `unsloth/Qwen3.5-2B-GGUF` **Q8_0** (~2.5 GB; highest practical quant for
  a 2B → best tool-call reliability, fits the 12 GB GPU fully).
- Tools: `create_poll`, `edit_poll` (Telegram-poll-shaped). See
  [poll_tools.py](poll_tools.py).
- Suites: [cases.py](cases.py) (10 EN + 12 UZ) and
  [cases_uz_extra.py](cases_uz_extra.py) (15 extra UZ).
- Run with: `venv/bin/python tooltest/run_tests.py` and
  `venv/bin/python tooltest/run_uz_extra.py`.

## Headline results (both rounds combined, 37 cases)

| Model        | Routing | create_poll | edit_poll | general (no-trigger) | args when calling | UZ routing | latency avg |
|--------------|:-------:|:-----------:|:---------:|:--------------------:|:-----------------:|:----------:|:-----------:|
| gemma-4-12b  | **37/37 (100%)** | 18/18 | **8/8** | 11/11 | 25/25 | **27/27** | ~1.0 s |
| qwen3.5-2b   | 31/37 (84%) | **18/18** | 2/8 | 11/11 | 18/19 | 23/27 | ~0.6 s |

## What this means

**Gemma-4-12b is flawless** at tool calling in both English and Uzbek — correct
tool choice, correct arguments (anonymity, multiple-answers, quiz correct-index),
correct edits/close, and it never fires a tool on general questions (incl. traps
like "what were yesterday's poll results?"). Its Uzbek general answers are fluent
and correct.

**Qwen3.5-2B is excellent at the *main* task** — `create_poll` was **18/18**
including every flag and **perfect Uzbek**, mixed Russian/Uzbek, quizzes, and
5-option lists — and it **never over-triggers** on general questions (11/11). It
is ~2× faster per call. Its one real weakness is **`edit_poll` (2/8)**: it tends
to either not call a tool or misroute "add an option / remove an option" to
`create_poll`. It also dropped the `type=quiz` flag once (kept the correct index).

> Caveat on edit_poll: tests sent the edit request with **no prior poll in the
> conversation**, so "edit the last poll" had no referent. In a real bot the
> recent poll would be in history; that context would likely lift Qwen's edit
> score. Worth a follow-up test.

## Recommendation for this hardware (single 12 GB GPU, llama-swap)

- **Pick Config A (Gemma-only).** It's the most accurate and, critically,
  `llama-swap` keeps only **one** model resident at a time — Config B would swap
  Qwen→Gemma on *every* turn (cold-start each time). Gemma already serves general
  chat, so adding poll tools to it costs nothing extra and is 100% accurate.
- **Use Config B only if** you can host both models at once (more VRAM / 2nd GPU /
  run the 2B on CPU) and want a tiny fast front-end. Then Qwen3.5-2B is a great
  `create_poll` engine. For full poll CRUD either (a) keep `edit_poll` on Gemma,
  (b) add 1–2 few-shot edit examples to Qwen's prompt, or (c) try Qwen 4B/8B.
