#!/usr/bin/env python3
"""Calibration capture: run real cycles and write down the whole funnel.

**Measures. Decides nothing, changes nothing, sends nothing.** It runs
`scripts/run_session.py`'s loop against the account named by `--env` with
`--no-submit` forced on, and attaches a measurement observer to the cycle. No
config file is read for anything but its current values, none is written, and
the executor is never reached.

**Why it drives the real loop rather than re-implementing it.** The question
being asked is why the live funnel produces no candidates. A script that fetched
the chain and screened it its own way would answer that question about itself.
This one attaches to `run_cycle`'s observer hook, which is handed the cycle's own
contracts, its own snapshots, its own screener result and its own candidates,
after the funnel has produced them.

What lands in the JSONL, one object per cycle:

  * **contracts** — how many came back, over how many pages, by expiry.
  * **quote ages** — `as_of - latestQuote.t` for every contract that has a quote,
    as percentiles, for ALL strikes and separately for the near-the-money band.
    This is the number `quote_max_age_seconds` is a threshold on, and nobody has
    ever looked at its distribution.
  * **screener rejects** — by reason, and by whether the contract is near the
    money, because a threshold that only excludes far wings is a different
    problem from one that excludes the strikes we would actually trade.
  * **liquidity window** — for every ACCEPTED contract, which rule excluded it,
    evaluated as a short leg and as a long leg. Plus the pair analysis: for each
    viable short leg, whether a wing exists at the width and what stopped it.
  * **candidates** — what actually got built, if anything.

Spot is read from the equities feed (`/v2/stocks/SPY/snapshot`, IEX) rather than
from the option chain, deliberately: the chain's freshness is the thing being
measured, and a spot derived from it would be least reliable exactly when the
measurement matters most. Put-call parity over the chain is the fallback, and it
is recorded as such.

Usage:
    python scripts/calibrate.py --env .env --cycles 10 --interval 60
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from glassbox.datafeed import parse_wire_ts  # noqa: E402

from dry_run import liquidity_reasons, quote_of  # noqa: E402
from run_cycle import build_context  # noqa: E402
from run_session import run_session  # noqa: E402

#: The near-the-money band, as a fraction of spot. Not a threshold and not a
#: proposal: it is the width of the window this capture reports separately,
#: chosen because a 5-wide SPY vertical placed by the current delta band sits
#: inside it. Widening or narrowing it changes what the report says, not what
#: anything does.
NEAR_THE_MONEY_PCT = 0.03

#: The width the proposal helper builds at, restated here ONLY so the pair
#: analysis can ask the same question the builder asks. It reads the builder's
#: value rather than owning one.
from run_cycle import _WIDTH as WIDTH  # noqa: E402,E402

_PERCENTILES = (0, 10, 25, 50, 75, 90, 95, 99, 100)


def percentiles(values):
    """Percentiles by nearest-rank, so every reported number is a real observation.

    No interpolation: an interpolated p95 of a quote age is a quote that does not
    exist, and the point of this capture is to describe quotes that do.
    """
    if not values:
        return {}
    ordered = sorted(values)
    out = {"n": len(ordered)}
    for pct in _PERCENTILES:
        rank = max(1, min(len(ordered), int(round(pct / 100 * len(ordered)))))
        out[f"p{pct}"] = round(ordered[rank - 1], 3)
    out["mean"] = round(sum(ordered) / len(ordered), 3)
    return out


def spot_from_equities(feed):
    """SPY's own last trade/quote, off the free IEX feed. Read-only."""
    try:
        body = feed.get_raw("data", "/v2/stocks/SPY/snapshot", {"feed": "iex"})
    except Exception as exc:                              # noqa: BLE001
        return None, f"unavailable: {type(exc).__name__}"
    quote = body.get("latestQuote") or {}
    bid, ask = quote.get("bp"), quote.get("ap")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 < ask:
        return round((bid + ask) / 2, 4), "equities_midpoint"
    trade = body.get("latestTrade") or {}
    if isinstance(trade.get("p"), (int, float)):
        return round(float(trade["p"]), 4), "equities_last_trade"
    return None, "no usable equities quote"


def quote_age(snapshot, as_of):
    quote = (snapshot or {}).get("latestQuote") or {}
    stamp = quote.get("t")
    if not isinstance(stamp, str):
        return None
    try:
        return (as_of - parse_wire_ts(stamp)).total_seconds()
    except (ValueError, TypeError):
        return None


def strike_of(contract):
    try:
        return float(contract.get("strike_price"))
    except (TypeError, ValueError):
        return None


class Capture:
    """The observer. Turns one cycle's raw materials into one JSONL record."""

    def __init__(self, path, feed, thresholds):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.feed = feed
        self.thresholds = thresholds
        self.records = []

    def __call__(self, funnel):
        record = self.measure(funnel)
        self.records.append(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    # -- the measurement ---------------------------------------------------

    def measure(self, funnel):
        result = funnel["result"]
        record = {
            "cycle_id": result["cycle_id"],
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "as_of": result["as_of"],
            "market_open": result["market_open"],
            "skipped": result["skipped"],
            "screened": result.get("screened"),
            "exclusions": result.get("exclusions"),
            "candidates_built": result.get("candidates", 0),
        }

        contracts = (funnel.get("contracts") or {}).get("option_contracts")
        if not contracts:
            record["note"] = "no chain was fetched on this cycle"
            return record

        as_of = funnel["as_of"]
        snapshots = (funnel.get("snapshots") or {}).get("snapshots") or {}
        screened = funnel.get("screened") or {}
        accepted = screened.get("accepted") or []
        rejected = screened.get("rejected") or []

        spot, spot_source = spot_from_equities(self.feed)
        if spot is None:
            spot, spot_source = funnel.get("spot"), "put_call_parity_over_the_chain"
        record["spot"] = spot
        record["spot_source"] = spot_source

        by_symbol = {c["symbol"]: c for c in contracts}
        near = self._near_the_money(by_symbol, spot)

        record["contracts"] = {
            "fetched": len(contracts),
            "pages": (funnel.get("contracts") or {}).get("pages"),
            "by_expiry": self._count(c.get("expiration_date") for c in contracts),
            "by_type": self._count(c.get("type") for c in contracts),
            "near_the_money": len(near),
            "near_the_money_band_pct": NEAR_THE_MONEY_PCT,
        }

        # -- quote ages, the number quote_max_age_seconds is a threshold on --
        ages, ages_near, no_quote, no_quote_near = [], [], 0, 0
        for symbol in by_symbol:
            age = quote_age(snapshots.get(symbol), as_of)
            if age is None:
                no_quote += 1
                if symbol in near:
                    no_quote_near += 1
                continue
            ages.append(age)
            if symbol in near:
                ages_near.append(age)
        max_age = self.thresholds["quote_max_age_seconds"]
        positive = [age for age in ages if age >= 0]
        record["quote_age_seconds"] = {
            "all": percentiles(ages),
            "near_the_money": percentiles(ages_near),
            # The screener rejects a NEGATIVE age too, and correctly: a quote
            # dated after the `as_of` that claims to precede it cannot be
            # reconciled with the read. So the two failures are separated here,
            # because they have completely different answers.
            "negative_age": sum(1 for age in ages if age < 0),
            "negative_age_near_the_money": sum(1 for age in ages_near if age < 0),
            "non_negative_only": percentiles(positive),
            "non_negative_only_near_the_money": percentiles(
                [age for age in ages_near if age >= 0]),
            "no_parseable_quote": no_quote,
            "no_parseable_quote_near_the_money": no_quote_near,
            "threshold_in_force": max_age,
        }

        # -- screener rejects, split by whether we would ever trade the strike --
        reasons, reasons_near = {}, {}
        stale_only, stale_only_near = 0, 0
        for entry in rejected:
            codes = set(entry["reasons"])
            for reason in codes:
                reasons[reason] = reasons.get(reason, 0) + 1
                if entry["symbol"] in near:
                    reasons_near[reason] = reasons_near.get(reason, 0) + 1
            if codes == {"stale_quote"}:
                stale_only += 1
                if entry["symbol"] in near:
                    stale_only_near += 1
        record["reject_reasons"] = {
            "all": reasons, "near_the_money": reasons_near,
            "rejected_total": len(rejected), "accepted_total": len(accepted),
            # The number that says whether freshness is the BINDING constraint:
            # contracts whose ONLY defect was the quote's age. Everything else
            # rejected has a second reason that no freshness setting can fix.
            "stale_quote_only": stale_only,
            "stale_quote_only_near_the_money": stale_only_near,
        }

        # -- the two counterfactuals, computed per contract on this cycle -----
        # (a) what a different quote_max_age_seconds would admit, and
        # (b) what SHIFTING as_of forward by d seconds would admit — which is
        #     what stamping the read at the moment it FINISHED would do
        #     (dry_run.stamped: "a read is true as of when it finished"). Under
        #     a shift of d, a quote's age becomes age + d.
        # Both are reported as the count that would clear the WHOLE screener,
        # not just the freshness test, because a contract with null greeks is
        # not admitted by any amount of patience.
        other_defects = {entry["symbol"] for entry in rejected
                         if set(entry["reasons"]) - {"stale_quote"}}
        ages_by_symbol = {}
        for symbol in by_symbol:
            age = quote_age(snapshots.get(symbol), as_of)
            if age is not None:
                ages_by_symbol[symbol] = age

        def admitted(limit, shift):
            total = near_count = 0
            for symbol, age in ages_by_symbol.items():
                if symbol in other_defects:
                    continue
                shifted = age + shift
                if 0 <= shifted <= limit:
                    total += 1
                    if symbol in near:
                        near_count += 1
            return {"all": total, "near_the_money": near_count}

        record["would_admit"] = {
            "note": ("counts that would clear the WHOLE screener, not only the "
                     "freshness test; contracts with any other reject reason are "
                     "excluded because no freshness setting admits them"),
            "by_max_age_seconds": {
                str(limit): admitted(limit, 0)
                for limit in (60, 300, 900, 1800, 3600, 7200, 21600, 86400)},
            "by_as_of_shift_seconds_at_current_max_age": {
                str(shift): admitted(max_age, shift)
                for shift in (0, 1, 2, 3, 5, 10, 30)},
        }

        # -- the liquidity window, per accepted contract, per rule ------------
        record["liquidity_window"] = self._window(accepted, snapshots, by_symbol, spot)

        record["candidates"] = [
            {"structure": c["structure"], "qty": c["qty"],
             "net_debit_credit": c["net_debit_credit"],
             "legs": [leg["symbol"] for leg in c["legs"]]}
            for c in (funnel.get("candidates") or [])
        ]
        return record

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _count(values):
        counts = {}
        for value in values:
            counts[str(value)] = counts.get(str(value), 0) + 1
        return dict(sorted(counts.items()))

    def _near_the_money(self, by_symbol, spot):
        if not spot:
            return set()
        span = spot * NEAR_THE_MONEY_PCT
        return {symbol for symbol, contract in by_symbol.items()
                if (strike := strike_of(contract)) is not None
                and abs(strike - spot) <= span}

    def _window(self, accepted, snapshots, by_symbol, spot):
        """Which liquidity rule excluded which accepted contract, and the pairs.

        Calls the harness's own `liquidity_reasons`, so this reports the rule
        that actually ran rather than a restatement of it.
        """
        window = self.thresholds.get("liquidity_window")
        if window is None:
            return {"configured": False}

        short_out, long_out = {}, {}
        viable_short, viable_long = set(), set()
        near = self._near_the_money(by_symbol, spot)
        short_out_near = {}

        for contract in accepted:
            symbol = contract["symbol"]
            reasons = liquidity_reasons(symbol, window, by_symbol, snapshots,
                                        short_leg=True)
            if reasons:
                for reason in reasons:
                    short_out[reason] = short_out.get(reason, 0) + 1
                    if symbol in near:
                        short_out_near[reason] = short_out_near.get(reason, 0) + 1
            else:
                viable_short.add(symbol)

            reasons = liquidity_reasons(symbol, window, by_symbol, snapshots,
                                        short_leg=False)
            if reasons:
                for reason in reasons:
                    long_out[reason] = long_out.get(reason, 0) + 1
            else:
                viable_long.add(symbol)

        # The pair question the builder actually asks: puts below spot, a wing
        # WIDTH lower, both sides clearing the window.
        puts = [c for c in accepted if c["option_type"] == "put"
                and (spot is None or c["strike"] < spot)]
        by_key = {(c["expiry"], c["strike"]): c for c in puts}
        pairs = {"short_viable": 0, "no_wing_at_width": 0, "wing_excluded": 0,
                 "complete": 0, "complete_symbols": []}
        for short in puts:
            if short["symbol"] not in viable_short:
                continue
            pairs["short_viable"] += 1
            wing = by_key.get((short["expiry"], short["strike"] - WIDTH))
            if wing is None:
                pairs["no_wing_at_width"] += 1
            elif wing["symbol"] not in viable_long:
                pairs["wing_excluded"] += 1
            else:
                pairs["complete"] += 1
                pairs["complete_symbols"].append([short["symbol"], wing["symbol"]])

        # What the delta band and the OI floor would have admitted at other
        # settings, on this cycle's own accepted set. Evidence for a number.
        deltas = []
        interest = []
        for contract in accepted:
            greeks = (snapshots.get(contract["symbol"]) or {}).get("greeks") or {}
            delta = greeks.get("delta")
            if isinstance(delta, (int, float)) and not isinstance(delta, bool):
                deltas.append(abs(delta))
            raw = (by_symbol.get(contract["symbol"]) or {}).get("open_interest")
            try:
                interest.append(int(float(raw)))
            except (TypeError, ValueError):
                pass

        return {
            "configured": True,
            "settings": {k: v for k, v in window.items() if not k.startswith("_")},
            "short_leg_excluded_by": short_out,
            "short_leg_excluded_by_near_the_money": short_out_near,
            "long_leg_excluded_by": long_out,
            "viable_short_legs": len(viable_short),
            "viable_long_legs": len(viable_long),
            "pairs_at_width": dict(pairs, width=WIDTH),
            "abs_delta_of_accepted": percentiles(deltas),
            "open_interest_of_accepted": percentiles(interest),
            "accepted_in_delta_band": sum(
                1 for d in deltas
                if window["short_leg_abs_delta_min"] <= d <= window["short_leg_abs_delta_max"]),
            "accepted_over_oi_floor": sum(
                1 for oi in interest if oi >= window["min_open_interest"]),
        }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, default=None, metavar="FILE",
                        help="which env file, and therefore WHICH ACCOUNT. Required.")
    parser.add_argument("--cycles", type=int, default=10, metavar="N")
    parser.add_argument("--interval", type=int, default=60, metavar="SECONDS")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="JSONL to append to. Defaults to "
                             "data/calibration_<UTC date>.jsonl (gitignored).")
    parser.add_argument("--stop", default=None, metavar="HH:MM|ISO",
                        help="hard stop. Defaults to two hours from now, bounded "
                             "by --cycles anyway.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    started = datetime.now(timezone.utc)
    out = Path(args.out) if args.out else (
        REPO / "data" / f"calibration_{started.strftime('%Y%m%d')}.jsonl")

    # submit=False is not a flag here, it is the only value. A calibration run
    # that could place an order is not a calibration run.
    context = build_context(args.env, mode="autopilot", submit=False)
    capture = Capture(out, context.feed, dict(
        context.screener_thresholds,
        liquidity_window=context.governor_thresholds.get("liquidity_window")))
    context.observer = capture

    stop_at = started + timedelta(hours=2)
    if args.stop:
        from run_session import parse_stop
        stop_at = parse_stop(args.stop, started)

    print("=" * 78)
    print("GlassBox CALIBRATION CAPTURE — measures only, sends nothing")
    print(f"profile          : {context.profile['name'].upper()}  "
          f"account={context.profile['account_number']}  "
          f"scored={'YES' if context.profile['scored'] else 'no'}")
    print(f"cycles           : {args.cycles} at {args.interval}s")
    print(f"writing          : {out}")
    print(f"submit           : NO — forced off, not a flag")
    print(f"quote_max_age    : {context.screener_thresholds['quote_max_age_seconds']}s "
          f"(in force, NOT changed by this run)")
    window = context.governor_thresholds.get("liquidity_window") or {}
    print(f"liquidity window : oi>={window.get('min_open_interest')} "
          f"|delta| {window.get('short_leg_abs_delta_min')}"
          f"..{window.get('short_leg_abs_delta_max')} "
          f"(in force, NOT changed by this run)")
    print("=" * 78)

    code = run_session(
        context, stop_at=stop_at, interval_seconds=args.interval,
        pause_file=REPO / context.runner["pause_file"],
        max_consecutive_errors=context.runner["max_consecutive_errors"],
        max_cycles=args.cycles,
    )
    print("=" * 78)
    print(f"CAPTURE ENDED, exit={code}  records={len(capture.records)}  file={out}")
    print("=" * 78)
    return code


if __name__ == "__main__":
    sys.exit(main())
