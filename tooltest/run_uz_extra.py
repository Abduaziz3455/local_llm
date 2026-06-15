#!/usr/bin/env python3
"""Run the extended Uzbek suite (cases_uz_extra) on both models, reusing the
evaluation logic from run_tests.py."""
import sys
sys.path.insert(0, "tooltest")
sys.path.insert(0, ".")

import run_tests                       # noqa: E402
from cases_uz_extra import CASES       # noqa: E402

# Point the harness's case list at the extended Uzbek set.
run_tests.CASES = CASES


def main():
    models = sys.argv[1:] or ["gemma-4-12b", "qwen3.5-2b"]
    summaries = []
    results = {}
    for m in models:
        res = run_tests.run_model(m)
        results[m] = res
        summaries.append(run_tests.summarize(m, res))

    print(f"\n{'='*78}\n  UZBEK-EXTENDED COMPARISON\n{'='*78}")
    hdr = f"{'model':14} {'routing':>9} {'tool':>7} {'general':>8} {'args':>7}"
    print(hdr)
    print("-" * len(hdr))
    for s in summaries:
        print(f"{s['model']:14} {s['routing']:>9} {s['tool']:>7} {s['general']:>8} {s['args']:>7}")

    import json
    with open("tooltest/results_uz_extra.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nSaved to tooltest/results_uz_extra.json")


if __name__ == "__main__":
    main()
