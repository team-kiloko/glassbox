"""GB-S — chain-screener contract suite.

The acceptance gate for the chain screener (CLAUDE.md: "a module merges when its
suite passes"). The screener's single non-negotiable behaviour is FAIL CLOSED:
a contract it cannot fully price from the data in front of it is REJECTED. It
never imputes, interpolates, defaults, or retries its way to an accept.

Two bands:

  GB-S-F**  fixture integrity — runs today, must pass. Guards the golden data.
  GB-S-**   screener behaviour — xfail until the screener module lands, then
            runs for real automatically (see conftest.requires_screener).

The screener interface these tests call is GB_INTERFACES.md shape 6, SIGNED and
IN FORCE as of 2026-09-02. The seam is the authority; conftest.py restates it.
"""

from __future__ import annotations

import re

import pytest

from conftest import (
    has_ask,
    has_bid,
    has_complete_greeks,
    parse_ts,
    quote_age_seconds,
    reasons_for,
    requires_screener,
    run_screener,
    symbols_of,
)

OCC = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
                 r"(?P<cp>[CP])(?P<strike>\d{8})$")

HEALTHY = ["SPY260918C00640000", "SPY260918P00635000"]
NULL_GREEKS = ["SPY260918C00500000", "SPY260918C00780000"]
NO_BID = ["SPY260918C00780000", "SPY260918P00470000"]
STALE = ["SPY260918C00655000"]
NO_SNAPSHOT = ["SPY260918C00700000"]
NO_ASK = ["SPY260918C00760000"]


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_s_f01_contracts_match_alpaca_shape(contracts):
    """GB-S-F01: contracts fixture matches /v2/options/contracts, numerics as strings."""
    required = {
        "id", "symbol", "name", "status", "tradable", "expiration_date",
        "root_symbol", "underlying_symbol", "underlying_asset_id", "type",
        "style", "strike_price", "multiplier", "size", "open_interest",
        "close_price",
    }
    assert contracts, "fixture must not be empty"
    for contract in contracts:
        missing = required - set(contract)
        assert not missing, f"{contract.get('symbol')} missing {sorted(missing)}"

        # This endpoint returns numerics as STRINGS. A screener that compares a
        # strike across endpoints without casting is silently wrong.
        for field in ("strike_price", "multiplier", "size", "open_interest",
                      "close_price"):
            assert isinstance(contract[field], str), (
                f"{contract['symbol']}.{field} must be a string, "
                f"got {type(contract[field]).__name__}"
            )

        # OCC symbol must agree with the structured fields beside it.
        match = OCC.match(contract["symbol"])
        assert match, f"{contract['symbol']} is not a valid OCC symbol"
        assert match["cp"] == contract["type"][0].upper()
        assert float(match["strike"]) / 1000 == float(contract["strike_price"])
        assert (
            f"20{match['yy']}-{match['mm']}-{match['dd']}"
            == contract["expiration_date"]
        )


def test_gb_s_f02_snapshots_match_alpaca_shape(snapshots, contracts):
    """GB-S-F02: snapshots fixture matches the indicative-feed shape."""
    contract_symbols = {c["symbol"] for c in contracts}
    assert set(snapshots) <= contract_symbols, "snapshot for an unknown contract"

    for symbol, snapshot in snapshots.items():
        quote = snapshot.get("latestQuote")
        assert quote, f"{symbol} has no latestQuote"
        for field in ("ap", "as", "bp", "bs", "t"):
            assert field in quote, f"{symbol}.latestQuote missing {field}"
        assert isinstance(quote["ap"], (int, float))
        assert isinstance(quote["bp"], (int, float))
        parse_ts(quote["t"])  # raises if not RFC3339

        # greeks is either null or a complete mapping — never partial.
        greeks = snapshot.get("greeks")
        assert greeks is None or isinstance(greeks, dict)
        if isinstance(greeks, dict):
            assert set(greeks) == {"delta", "gamma", "theta", "vega", "rho"}
            assert all(v is not None for v in greeks.values())

    # Exactly one contract is deliberately snapshot-less (feeds GB-S-09).
    assert contract_symbols - set(snapshots) == set(NO_SNAPSHOT)


def test_gb_s_f03_defect_cases_are_actually_defective(snapshots, as_of, thresholds):
    """GB-S-F03: every labelled defect is really present, and really isolated."""
    required_greeks = thresholds["required_greeks"]
    budget = thresholds["quote_max_age_seconds"]

    for symbol in NULL_GREEKS:
        assert snapshots[symbol]["greeks"] is None, f"{symbol} should have null greeks"

    for symbol in NO_BID:
        assert not has_bid(snapshots[symbol]), f"{symbol} should have no bid"
        quote = snapshots[symbol]["latestQuote"]
        assert quote["ap"] > 0, f"{symbol} should still show an ask (one-sided)"

    for symbol in STALE:
        snapshot = snapshots[symbol]
        assert quote_age_seconds(snapshot, as_of) > budget, f"{symbol} not stale"
        # The trap: stale but otherwise immaculate.
        assert has_complete_greeks(snapshot, required_greeks)
        assert has_bid(snapshot)

    for symbol in HEALTHY:
        snapshot = snapshots[symbol]
        assert has_complete_greeks(snapshot, required_greeks)
        assert has_bid(snapshot)
        assert 0 <= quote_age_seconds(snapshot, as_of) <= budget

    for symbol in NO_ASK:
        snapshot = snapshots[symbol]
        assert not has_ask(snapshot), f"{symbol} should have no ask"
        # The mirror trap: a live bid must not rescue it.
        assert has_bid(snapshot), f"{symbol} should still show a bid (one-sided)"
        assert has_complete_greeks(snapshot, required_greeks)
        assert quote_age_seconds(snapshot, as_of) <= budget

    # P00470000 isolates missing_bid: greeks complete, quote fresh.
    isolated = snapshots["SPY260918P00470000"]
    assert has_complete_greeks(isolated, required_greeks)
    assert quote_age_seconds(isolated, as_of) <= budget
    assert not has_bid(isolated)


def test_gb_s_f04_golden_covers_every_contract_once(golden, contracts):
    """GB-S-F04: the golden file is total, and uses only the agreed reason codes."""
    expected = golden["expected"]
    assert set(expected) == {c["symbol"] for c in contracts}, (
        "golden must cover every contract exactly once"
    )
    vocabulary = set(golden["reason_vocabulary"])
    for symbol, verdict in expected.items():
        assert isinstance(verdict["accept"], bool)
        assert set(verdict["reasons"]) <= vocabulary, f"{symbol}: unknown reason code"
        # An accept has no reasons; a reject must say why.
        assert bool(verdict["reasons"]) is not verdict["accept"], (
            f"{symbol}: accept/reasons disagree"
        )


# ---------------------------------------------------------------------------
# Screener behaviour — xfail until the module lands
# ---------------------------------------------------------------------------

@requires_screener
def test_gb_s_01_rejects_null_greeks(contracts_body, snapshots_body, as_of, thresholds):
    """GB-S-01: a contract with null greeks is REJECTED. Never estimated."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in NULL_GREEKS:
        assert symbol not in symbols_of(accepted)
        assert "null_greeks" in reasons_for(rejected, symbol)


@requires_screener
def test_gb_s_02_rejects_missing_bid(contracts_body, snapshots_body, as_of, thresholds):
    """GB-S-02: a contract with no bid is REJECTED. Never priced off the ask alone."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in NO_BID:
        assert symbol not in symbols_of(accepted)
        assert "missing_bid" in reasons_for(rejected, symbol)


@requires_screener
def test_gb_s_03_rejects_stale_quote(contracts_body, snapshots_body, as_of, thresholds):
    """GB-S-03: a quote older than the freshness budget is REJECTED."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in STALE:
        assert symbol not in symbols_of(accepted)
        assert "stale_quote" in reasons_for(rejected, symbol)


@requires_screener
def test_gb_s_04_accepts_healthy_near_the_money(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-04: fail-closed must not mean fail-everything — healthy contracts pass."""
    accepted, _ = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    assert symbols_of(accepted) == set(HEALTHY)


@requires_screener
def test_gb_s_05_never_guesses(contracts_body, snapshots_body, as_of, thresholds):
    """GB-S-05: THE invariant. Nothing is accepted that the raw data cannot support.

    No imputed greeks, no ask-derived mid standing in for an absent bid, no
    tolerance stretched to admit a stale quote.
    """
    accepted, _ = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    snapshots = snapshots_body["snapshots"]
    for symbol in symbols_of(accepted):
        assert symbol in snapshots, f"{symbol} accepted with no snapshot at all"
        snapshot = snapshots[symbol]
        assert has_complete_greeks(snapshot, thresholds["required_greeks"]), (
            f"{symbol} accepted without complete greeks in the source data"
        )
        assert has_bid(snapshot), f"{symbol} accepted without a real bid"
        assert quote_age_seconds(snapshot, as_of) <= thresholds["quote_max_age_seconds"], (
            f"{symbol} accepted on a stale quote"
        )


@requires_screener
def test_gb_s_06_every_rejection_is_explained(
    contracts_body, snapshots_body, as_of, thresholds, golden
):
    """GB-S-06: rejections carry machine-readable reason codes, for the ledger."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    vocabulary = set(golden["reason_vocabulary"])

    # Total partition: every contract lands in exactly one bucket.
    all_symbols = {c["symbol"] for c in contracts_body["option_contracts"]}
    assert symbols_of(accepted) | symbols_of(rejected) == all_symbols
    assert not (symbols_of(accepted) & symbols_of(rejected))

    for entry in rejected:
        symbol = entry["symbol"] if isinstance(entry, dict) else entry.symbol
        codes = set(entry["reasons"] if isinstance(entry, dict) else entry.reasons)
        assert codes, f"{symbol} rejected with no reason"
        assert codes <= vocabulary, f"{symbol}: reasons outside vocabulary: {codes}"


@requires_screener
def test_gb_s_07_one_sided_quote_is_rejected(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-07: a live ask does not rescue a contract that has no bid."""
    accepted, _ = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    snapshot = snapshots_body["snapshots"]["SPY260918P00470000"]
    assert snapshot["latestQuote"]["ap"] > 0 and snapshot["latestQuote"]["as"] > 0
    assert "SPY260918P00470000" not in symbols_of(accepted)


@requires_screener
def test_gb_s_08_zero_bid_is_missing_not_free(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-08: bp=0/bs=0 means NO BID. Reading it as a $0.00 price is the bug."""
    _, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in NO_BID:
        quote = snapshots_body["snapshots"][symbol]["latestQuote"]
        assert quote["bp"] == 0 and quote["bs"] == 0, "fixture drift"
        assert "missing_bid" in reasons_for(rejected, symbol), (
            f"{symbol}: zero bid must read as missing, not as a valid $0.00 bid"
        )


@requires_screener
def test_gb_s_09_missing_snapshot_is_rejected(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-09: a contract with no snapshot is rejected, not skipped or retried."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in NO_SNAPSHOT:
        assert symbol not in symbols_of(accepted)
        assert symbol in symbols_of(rejected), (
            f"{symbol} vanished: absence must be an explicit reject, not a silent drop"
        )
        assert "no_snapshot" in reasons_for(rejected, symbol)


@requires_screener
def test_gb_s_10_is_deterministic(contracts_body, snapshots_body, as_of, thresholds):
    """GB-S-10: identical inputs give identical verdicts. No clock, no randomness."""
    first = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    second = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    assert symbols_of(first[0]) == symbols_of(second[0])
    assert symbols_of(first[1]) == symbols_of(second[1])
    for symbol in symbols_of(first[1]):
        assert reasons_for(first[1], symbol) == reasons_for(second[1], symbol)


@requires_screener
def test_gb_s_11_matches_golden_verdicts(
    contracts_body, snapshots_body, as_of, thresholds, golden
):
    """GB-S-11: the whole slice matches the golden file, symbol by symbol."""
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    accepted_symbols = symbols_of(accepted)

    for symbol, verdict in golden["expected"].items():
        if verdict["accept"]:
            assert symbol in accepted_symbols, f"{symbol} should have been accepted"
        else:
            assert symbol not in accepted_symbols, f"{symbol} should have been rejected"
            assert reasons_for(rejected, symbol) == set(verdict["reasons"]), (
                f"{symbol}: reason codes differ from golden"
            )


@requires_screener
def test_gb_s_12_accepted_contracts_carry_leg_fields(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-12: accepted output slots into GB_INTERFACES.md shape #2 `legs[]`.

    PROPOSED — the seam shape itself is pending human sign-off.
    """
    accepted, _ = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for entry in accepted:
        fields = entry if isinstance(entry, dict) else vars(entry)
        for name in ("symbol", "option_type", "strike", "expiry"):
            assert name in fields, f"accepted entry missing {name}"
        assert fields["option_type"] in ("call", "put")
        assert isinstance(fields["strike"], (int, float)), "strike must be numeric"
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", fields["expiry"])


@requires_screener
def test_gb_s_13_rejects_missing_ask(
    contracts_body, snapshots_body, as_of, thresholds
):
    """GB-S-13: a contract with no ask is REJECTED, with `missing_ask`.

    The mirror of GB-S-02, and not mere symmetry: `thresholds` requires a
    TWO-SIDED quote, and a vertical BUYS a leg, so an absent offer is
    un-executable on the long side. C00760000 isolates it — complete greeks,
    fresh quote, a real bid — so `missing_ask` is the only thing standing
    between it and acceptance, and it must be rejected under its OWN code
    rather than mislabelled as `missing_bid` (GB_INTERFACES.md shape 6,
    DECIDED 2026-09-02).
    """
    accepted, rejected = run_screener(contracts_body, snapshots_body, as_of, thresholds)
    for symbol in NO_ASK:
        quote = snapshots_body["snapshots"][symbol]["latestQuote"]
        assert quote["ap"] == 0 and quote["as"] == 0, "fixture drift"
        assert quote["bp"] > 0 and quote["bs"] > 0, "fixture drift"
        assert symbol not in symbols_of(accepted)
        assert reasons_for(rejected, symbol) == {"missing_ask"}, (
            f"{symbol}: zero ask must read as missing, under its own reason code"
        )
