#!/usr/bin/env python
"""Run the Nirikshan AI evaluation harness and print a JSON report.

Usage:
    python evaluation/run_eval.py                # all deterministic scenarios
    python evaluation/run_eval.py db-exhaustion  # a subset

Exit code is non-zero if the suite fails its thresholds, so CI can gate on it.
"""

from __future__ import annotations

import json
import sys

from nirikshan.ai.evaluation import run_evaluation


def main() -> int:
    scenarios = sys.argv[1:] or None
    report = run_evaluation(scenarios)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    if not report.passed:
        print("\nEVALUATION FAILED:", report.failures, file=sys.stderr)
        return 1
    print("\nEVALUATION PASSED", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
