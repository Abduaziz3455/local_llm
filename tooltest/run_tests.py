#!/usr/bin/env python3
"""
Poll tool-calling evaluation harness.

Goal: measure how well **gemma-4-12b** and **qwen3.5-2b** decide *when* to call
a poll tool and *with what arguments* — across English and Uzbek prompts.

Two configurations this informs:
  Config A:  Gemma does tool-calling AND answers general questions.
  Config B:  Qwen3.5-2B does tool-calling, Gemma answers general questions.

The general-answer quality is Gemma's in both configs, so the only thing that
differs between A and B is the *tool-caller*. This harness therefore runs the
SAME suite against each model as the tool-caller and compares them, then shows
Gemma's text answers for the general questions (the path both configs share).

Usage:
    python run_tests.py                 # full run, both models
    python run_tests.py gemma-4-12b     # one model only
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:5002/v1/chat/completions"
API_KEY = "local"

sys.path.insert(0, ".")
sys.path.insert(0, "tooltest")
from poll_tools import TOOLS           # noqa: E402
from cases import CASES                # noqa: E402

SYSTEM = (
    "You are a helpful assistant in a group chat that can manage polls. "
    "You have two tools: create_poll and edit_poll. "
    "When the user asks to create/start/set up a poll, survey, vote or quiz, "
    "call create_poll with the right question and options (and flags like "
    "anonymity, multiple answers, quiz correct answer when stated). "
    "When the user asks to change/add to/close an existing poll, call edit_poll. "
    "For any other message (greetings, factual questions, chit-chat, coding "
    "help) do NOT call a tool — just reply normally in the user's language. "
    "The user may write in English or Uzbek."
)


def chat(model, user_msg, with_tools=True, timeout=300):
    """One chat completion. Returns (assistant_message_dict, latency_s)."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,   # low temp for stable tool decisions
        "max_tokens": 512,
    }
    if with_tools:
        body["tools"] = TOOLS
        body["tool_choice"] = "auto"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE, data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    dt = time.time() - t0
    return resp["choices"][0]["message"], dt


def parse_tool_call(msg):
    """Return (func_name, args_dict) or (None, None) if no tool call."""
    tcs = msg.get("tool_calls") or []
    if not tcs:
        return None, None
    fn = tcs[0]["function"]
    name = fn["name"]
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {"_raw": fn.get("arguments")}
    return name, args


def check_args(check, args):
    """Score argument correctness against the `check` dict -> (passed, total, notes)."""
    if not check:
        return 0, 0, []
    passed = 0
    total = 0
    notes = []
    opts = args.get("options") or []
    opts_l = [str(o).lower() for o in opts]

    def add(ok, label):
        nonlocal passed, total
        total += 1
        passed += 1 if ok else 0
        notes.append(("ok " if ok else "MISS") + " " + label)

    if "n_options" in check:
        add(len(opts) == check["n_options"],
            f"n_options={check['n_options']} (got {len(opts)})")
    if "options_kw" in check:
        for kw in check["options_kw"]:
            add(any(kw.lower() in o for o in opts_l), f"option~'{kw}'")
    if "question_kw" in check:
        q = str(args.get("question", "")).lower()
        add(any(kw.lower() in q for kw in check["question_kw"]),
            f"question~{check['question_kw']}")
    if "multiple" in check:
        add(bool(args.get("allows_multiple_answers")) == check["multiple"],
            f"multiple={check['multiple']} (got {args.get('allows_multiple_answers')})")
    if "anonymous" in check:
        add(bool(args.get("is_anonymous", True)) == check["anonymous"],
            f"anonymous={check['anonymous']} (got {args.get('is_anonymous')})")
    if "type" in check:
        add(args.get("type") == check["type"],
            f"type={check['type']} (got {args.get('type')})")
    if "correct" in check:
        add(args.get("correct_option_id") == check["correct"],
            f"correct_id={check['correct']} (got {args.get('correct_option_id')})")
    if "action" in check:
        add(args.get("action") == check["action"],
            f"action={check['action']} (got {args.get('action')})")
    return passed, total, notes


def run_model(model):
    print(f"\n{'='*78}\n  TOOL-CALLING SUITE  ->  {model}\n{'='*78}")
    results = []
    for c in CASES:
        try:
            msg, dt = chat(model, c["msg"], with_tools=True)
        except Exception as e:                       # noqa: BLE001
            print(f"[{c['id']:14}] ERROR: {e}")
            results.append(dict(case=c["id"], lang=c["lang"], routing_ok=False,
                                args_ok=None, error=str(e)))
            continue
        name, args = parse_tool_call(msg)
        expect = c["expect"]
        # routing: did it (not) call the right tool?
        if expect is None:
            routing_ok = name is None
        else:
            routing_ok = name == expect
        ap, at, notes = (0, 0, [])
        if routing_ok and expect is not None:
            ap, at, notes = check_args(c.get("check"), args)
        args_ok = None if at == 0 else (ap == at)

        status = "PASS" if routing_ok and (args_ok in (None, True)) else \
                 ("ROUTE" if routing_ok else "FAIL")
        got = name if name else "(no tool / text)"
        argstr = ""
        if at:
            argstr = f"  args {ap}/{at}"
        print(f"[{c['id']:14}] {c['lang']}  exp={str(expect):11} got={got:13} "
              f"{status}{argstr}")
        if notes and (ap != at):
            print("                 " + " | ".join(notes))
        results.append(dict(case=c["id"], lang=c["lang"], expect=expect,
                            got=name, routing_ok=routing_ok, args_ok=args_ok,
                            args_passed=ap, args_total=at, latency=round(dt, 2),
                            text=(msg.get("content") or "")[:200], args=args))
    return results


def summarize(model, results):
    tool_cases = [r for r in results if r.get("expect") is not None]
    gen_cases = [r for r in results if r.get("expect") is None]
    route_ok = sum(1 for r in results if r.get("routing_ok"))
    tool_route = sum(1 for r in tool_cases if r.get("routing_ok"))
    gen_route = sum(1 for r in gen_cases if r.get("routing_ok"))
    arg_cases = [r for r in tool_cases if r.get("args_ok") is not None]
    arg_ok = sum(1 for r in arg_cases if r.get("args_ok"))
    # by language
    def lang_route(lang):
        rs = [r for r in results if r.get("lang") == lang]
        return sum(1 for r in rs if r.get("routing_ok")), len(rs)
    en_ok, en_n = lang_route("en")
    uz_ok, uz_n = lang_route("uz")
    lat = [r["latency"] for r in results if r.get("latency")]
    print(f"\n--- SUMMARY {model} ---")
    print(f"  Routing (right tool / no tool):  {route_ok}/{len(results)} "
          f"({100*route_ok/len(results):.0f}%)")
    print(f"    - tool cases (should call):    {tool_route}/{len(tool_cases)}")
    print(f"    - general cases (no call):     {gen_route}/{len(gen_cases)}")
    print(f"  Argument correctness:            {arg_ok}/{len(arg_cases)} "
          f"({100*arg_ok/max(1,len(arg_cases)):.0f}%)")
    print(f"  English routing:                 {en_ok}/{en_n}")
    print(f"  Uzbek routing:                   {uz_ok}/{uz_n}")
    if lat:
        print(f"  Latency avg/max:                 {sum(lat)/len(lat):.1f}s / {max(lat):.1f}s")
    return dict(model=model, routing=f"{route_ok}/{len(results)}",
                tool=f"{tool_route}/{len(tool_cases)}",
                general=f"{gen_route}/{len(gen_cases)}",
                args=f"{arg_ok}/{len(arg_cases)}",
                en=f"{en_ok}/{en_n}", uz=f"{uz_ok}/{uz_n}")


def show_general_answers(model, results):
    """Print Gemma's actual text answers for general questions (shared path)."""
    print(f"\n{'='*78}\n  GENERAL-QUESTION ANSWERS (text path, {model})\n{'='*78}")
    for r in results:
        if r.get("expect") is None and r.get("text"):
            print(f"[{r['case']:14}] {r['text']!r}")


def main():
    models = sys.argv[1:] or ["gemma-4-12b", "qwen3.5-2b"]
    all_summaries = []
    all_results = {}
    for m in models:
        res = run_model(m)
        all_results[m] = res
        all_summaries.append(summarize(m, res))
        if m == "gemma-4-12b":
            show_general_answers(m, res)

    print(f"\n{'='*78}\n  COMPARISON\n{'='*78}")
    hdr = f"{'model':14} {'routing':>9} {'tool':>7} {'general':>8} {'args':>7} {'EN':>6} {'UZ':>6}"
    print(hdr)
    print("-" * len(hdr))
    for s in all_summaries:
        print(f"{s['model']:14} {s['routing']:>9} {s['tool']:>7} {s['general']:>8} "
              f"{s['args']:>7} {s['en']:>6} {s['uz']:>6}")

    with open("tooltest/results.json", "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print("\nFull results saved to tooltest/results.json")


if __name__ == "__main__":
    main()
