#!/usr/bin/env python3
"""Read a calibration capture and print the tables the analysis rests on.

Read-only, offline, and separate from the capture on purpose: the capture is
attached to a live cycle and cannot be re-run against a market that has moved,
so the summary must be re-runnable against the file it already wrote.

Percentiles are per-cycle and are reported as a range ACROSS cycles rather than
pooled into one distribution. Pooling ten cycles taken minutes apart would
average over ten different market moments and describe none of them.

Usage:
    python scripts/summarize_calibration.py data/calibration_20260902.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path):
    return [json.loads(line) for line in
            Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def spread(values):
    """min / median / max of a per-cycle series, as a compact string."""
    clean = [v for v in values if v is not None]
    if not clean:
        return "—"
    clean.sort()
    median = clean[len(clean) // 2]
    fmt = (lambda v: f"{v:.2f}") if any(isinstance(v, float) for v in clean) else str
    return f"{fmt(clean[0])} / {fmt(median)} / {fmt(clean[-1])}"


def get(record, *path, default=None):
    node = record
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    records = load(argv[0])
    if not records:
        print("no records")
        return 1

    print(f"# {argv[0]} — {len(records)} cycles\n")

    print("## Per cycle\n")
    header = ("cycle", "as_of", "fetched", "acc", "stale", "neg_age", "stale_only",
              "null_gk", "no_bid", "short_ok", "pairs", "cand")
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for r in records:
        print("| " + " | ".join(str(x) for x in (
            r["cycle_id"],
            (r.get("as_of") or "")[11:19],
            get(r, "contracts", "fetched", default="—"),
            get(r, "reject_reasons", "accepted_total", default="—"),
            get(r, "reject_reasons", "all", "stale_quote", default=0),
            get(r, "quote_age_seconds", "negative_age", default="—"),
            get(r, "reject_reasons", "stale_quote_only", default="—"),
            get(r, "reject_reasons", "all", "null_greeks", default=0),
            get(r, "reject_reasons", "all", "missing_bid", default=0),
            get(r, "liquidity_window", "viable_short_legs", default="—"),
            get(r, "liquidity_window", "pairs_at_width", "complete", default="—"),
            r.get("candidates_built", 0),
        )) + " |")

    print("\n## Quote age, seconds — near the money (within 3% of spot)\n")
    print("Per-cycle percentile, reported as min / median / max ACROSS the cycles.\n")
    print("| pct | all strikes | near the money | near, non-negative only |")
    print("|---|---|---|---|")
    for pct in ("p0", "p10", "p25", "p50", "p75", "p90", "p95", "p100"):
        print(f"| {pct} | "
              f"{spread([get(r, 'quote_age_seconds', 'all', pct) for r in records])} | "
              f"{spread([get(r, 'quote_age_seconds', 'near_the_money', pct) for r in records])} | "
              f"{spread([get(r, 'quote_age_seconds', 'non_negative_only_near_the_money', pct) for r in records])} |")
    print(f"| n | {spread([get(r, 'quote_age_seconds', 'all', 'n') for r in records])} | "
          f"{spread([get(r, 'quote_age_seconds', 'near_the_money', 'n') for r in records])} | "
          f"{spread([get(r, 'quote_age_seconds', 'non_negative_only_near_the_money', 'n') for r in records])} |")
    print(f"\nNegative ages (quote dated AFTER as_of): all "
          f"{spread([get(r, 'quote_age_seconds', 'negative_age') for r in records])}, "
          f"near the money "
          f"{spread([get(r, 'quote_age_seconds', 'negative_age_near_the_money') for r in records])}")

    print("\n## Counterfactual A — a different quote_max_age_seconds\n")
    print("Contracts that would clear the WHOLE screener. Current setting: "
          f"{get(records[0], 'quote_age_seconds', 'threshold_in_force')}s.\n")
    limits = sorted(get(records[0], "would_admit", "by_max_age_seconds", default={}),
                    key=int)
    print("| max_age | admitted (all) | admitted (near the money) |")
    print("|---|---|---|")
    for limit in limits:
        print(f"| {limit}s | "
              f"{spread([get(r, 'would_admit', 'by_max_age_seconds', limit, 'all') for r in records])} | "
              f"{spread([get(r, 'would_admit', 'by_max_age_seconds', limit, 'near_the_money') for r in records])} |")

    print("\n## Counterfactual B — stamping as_of when the read FINISHED\n")
    print("Same threshold, every age shifted by +d seconds.\n")
    shifts = sorted(get(records[0], "would_admit",
                        "by_as_of_shift_seconds_at_current_max_age", default={}), key=int)
    print("| as_of shift | admitted (all) | admitted (near the money) |")
    print("|---|---|---|")
    for shift in shifts:
        print(f"| +{shift}s | "
              f"{spread([get(r, 'would_admit', 'by_as_of_shift_seconds_at_current_max_age', shift, 'all') for r in records])} | "
              f"{spread([get(r, 'would_admit', 'by_as_of_shift_seconds_at_current_max_age', shift, 'near_the_money') for r in records])} |")

    print("\n## The liquidity window, over the ACCEPTED set\n")
    rules = {}
    for r in records:
        for rule, count in (get(r, "liquidity_window", "short_leg_excluded_by",
                                default={}) or {}).items():
            rules.setdefault(rule, []).append(count)
    print("| short-leg rule | excluded (min/med/max) |")
    print("|---|---|")
    for rule, counts in sorted(rules.items()):
        print(f"| {rule} | {spread(counts)} |")
    print(f"\n| in delta band | {spread([get(r, 'liquidity_window', 'accepted_in_delta_band') for r in records])} |")
    print(f"| over OI floor | {spread([get(r, 'liquidity_window', 'accepted_over_oi_floor') for r in records])} |")
    print(f"| viable short legs | {spread([get(r, 'liquidity_window', 'viable_short_legs') for r in records])} |")
    print(f"| viable long legs | {spread([get(r, 'liquidity_window', 'viable_long_legs') for r in records])} |")

    print("\n### |delta| of the accepted set\n")
    print("| pct | " + " | ".join(str(r["cycle_id"]) for r in records) + " |")
    print("|" + "---|" * (len(records) + 1))
    for pct in ("p0", "p25", "p50", "p75", "p100"):
        print(f"| {pct} | " + " | ".join(
            str(get(r, "liquidity_window", "abs_delta_of_accepted", pct, default="—"))
            for r in records) + " |")

    print("\n### open interest of the accepted set\n")
    print("| pct | " + " | ".join(str(r["cycle_id"]) for r in records) + " |")
    print("|" + "---|" * (len(records) + 1))
    for pct in ("p0", "p25", "p50", "p75", "p100"):
        print(f"| {pct} | " + " | ".join(
            str(get(r, "liquidity_window", "open_interest_of_accepted", pct, default="—"))
            for r in records) + " |")

    print("\n## Pairs at the builder's width\n")
    for key in ("short_viable", "no_wing_at_width", "wing_excluded", "complete"):
        print(f"- **{key}**: {spread([get(r, 'liquidity_window', 'pairs_at_width', key) for r in records])}")
    print(f"- **candidates built**: "
          f"{spread([r.get('candidates_built') for r in records])}  "
          f"(total {sum(r.get('candidates_built', 0) for r in records)} over "
          f"{len(records)} cycles)")
    print(f"\nSpot: {spread([r.get('spot') for r in records])}  "
          f"(source: {records[0].get('spot_source')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
