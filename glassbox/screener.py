"""Chain screener — GB_INTERFACES.md shape 6.

Turns a raw options chain into the tradable universe the strategist is allowed
to build on. Its single non-negotiable behaviour is **fail closed**: a contract
this module cannot fully evaluate from the data in front of it is REJECTED,
with a machine-readable reason. It never imputes a greek, never prices off one
side of a quote, never stretches a tolerance, and never silently drops a
contract.

Purity, per the seam (6a) and CLAUDE.md:

* **No file I/O.** ``thresholds`` is a mapping the CALLER loads and passes in.
  This module does not know a config path and holds no copy of any tunable.
* **No clock.** Quote age is ``as_of - quote.t`` and nothing else (6b). A
  screener that consulted wall-clock time would return different verdicts for
  the same data depending on when it ran.
* **No randomness**, and no I/O of any other kind. Same inputs, same verdicts
  (GB-S-10).

Reason codes are the closed five-code vocabulary DECIDED (2026-09-02) in the
seam: ``null_greeks | missing_bid | missing_ask | stale_quote | no_snapshot``.
Nothing outside that set is ever emitted.

Note the division of labour between rejecting and raising. **Data quality is
rejected** — that is what the reason codes are for. **A schema violation is
raised**: a contract with no symbol, an unparseable strike, or a ``type`` that
is neither call nor put is not a market condition the screener has an opinion
about, it is a broken input, and there is no code in the closed vocabulary that
would honestly describe it. Raising fails closed too — nothing is accepted —
while staying loud instead of laundering a bug into a verdict.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

__all__ = ["screen_chain", "REASON_CODES"]

#: The closed vocabulary, in seam order. Rejection reasons are reported in this
#: order so output is stable (the seam says order is not significant; being
#: deterministic anyway costs nothing and makes diffs readable).
REASON_CODES = (
    "null_greeks",
    "missing_bid",
    "missing_ask",
    "stale_quote",
    "no_snapshot",
)

#: Threshold keys this module requires. There are no defaults on purpose: per
#: seam 6a a missing key is a caller error, not something to paper over with a
#: built-in value that would then be a second copy of a tunable.
_REQUIRED_THRESHOLDS = (
    "quote_max_age_seconds",
    "require_complete_greeks",
    "require_two_sided_quote",
    "required_greeks",
)

_EXPIRY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: RFC3339 out of Alpaca carries nanoseconds; datetime resolves microseconds.
#: Truncate deliberately rather than letting the parser fail (fixtures trap 7).
_SUBSECOND = re.compile(r"\.(\d{6})\d+")


def screen_chain(contracts, snapshots, as_of, thresholds):
    """Screen an options chain. See module docstring and GB_INTERFACES.md shape 6.

    Args:
        contracts: the parsed ``/v2/options/contracts`` body — a mapping with
            ``option_contracts``. A bare list of contracts is also accepted.
        snapshots: the parsed ``/v1beta1/options/snapshots`` body — a mapping
            with ``snapshots``. A bare ``{symbol: snapshot}`` mapping is also
            accepted.
        as_of: timezone-aware ``datetime`` that freshness is measured against.
        thresholds: mapping of tunables; see ``tests/fixtures/thresholds.PROPOSED.json``.

    Returns:
        ``{"accepted": [{symbol, option_type, strike, expiry}, ...],
           "rejected": [{symbol, reasons: [code, ...]}, ...]}``

        Every input contract appears in exactly one of the two lists, in input
        order.
    """
    missing = [key for key in _REQUIRED_THRESHOLDS if key not in thresholds]
    if missing:
        raise ValueError(
            "thresholds is missing required key(s): "
            + ", ".join(missing)
            + " — the caller loads the config and passes it in whole "
            "(GB_INTERFACES.md 6a); this module has no defaults"
        )
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")

    max_age = thresholds["quote_max_age_seconds"]
    require_greeks = thresholds["require_complete_greeks"]
    require_two_sided = thresholds["require_two_sided_quote"]
    required_greeks = thresholds["required_greeks"]

    by_symbol = _snapshot_index(snapshots)

    accepted = []
    rejected = []
    for contract in _contract_list(contracts):
        symbol, option_type, strike, expiry = _contract_fields(contract)
        snapshot = by_symbol.get(symbol)

        if snapshot is None:
            # Absence is an explicit reject, never a skip and never a retry.
            # Nothing else about the contract is evaluable, so no other code
            # could be honestly attached.
            rejected.append({"symbol": symbol, "reasons": ["no_snapshot"]})
            continue

        reasons = set()
        quote = snapshot.get("latestQuote")

        if require_greeks and not _greeks_complete(snapshot, required_greeks):
            reasons.add("null_greeks")

        if require_two_sided:
            if not _side_present(quote, "bp", "bs"):
                reasons.add("missing_bid")
            if not _side_present(quote, "ap", "as"):
                reasons.add("missing_ask")

        age = _quote_age_seconds(quote, as_of)
        # A quote we cannot age (absent, unparseable) and a quote dated AFTER
        # as_of are both unusable: the first cannot be shown fresh, the second
        # cannot be reconciled with the read it claims to precede. Neither is
        # accepted on the benefit of the doubt.
        if age is None or age < 0 or age > max_age:
            reasons.add("stale_quote")

        if reasons:
            rejected.append(
                {
                    "symbol": symbol,
                    "reasons": [c for c in REASON_CODES if c in reasons],
                }
            )
        else:
            accepted.append(
                {
                    "symbol": symbol,
                    "option_type": option_type,
                    "strike": strike,
                    "expiry": expiry,
                }
            )

    return {"accepted": accepted, "rejected": rejected}


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------

def _contract_list(contracts):
    if isinstance(contracts, dict):
        body = contracts.get("option_contracts")
        if body is None:
            raise ValueError("contracts body has no 'option_contracts'")
        return body
    return contracts


def _snapshot_index(snapshots):
    if isinstance(snapshots, dict) and "snapshots" in snapshots:
        index = snapshots["snapshots"]
    else:
        index = snapshots
    if not isinstance(index, dict):
        raise ValueError("snapshots must be a mapping of symbol -> snapshot")
    return index


def _contract_fields(contract):
    """Pull the shape-2 `legs[]` fields out of a contract record.

    Numerics arrive as STRINGS on this endpoint (fixtures trap 6); the cast is
    explicit here so nothing downstream compares a string strike to a float one.
    """
    symbol = contract.get("symbol")
    if not symbol:
        raise ValueError(f"contract has no symbol: {contract!r}")

    raw_type = contract.get("type")
    option_type = raw_type.lower() if isinstance(raw_type, str) else raw_type
    if option_type not in ("call", "put"):
        raise ValueError(f"{symbol}: type must be 'call' or 'put', got {raw_type!r}")

    try:
        strike = float(contract["strike_price"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            f"{symbol}: strike_price is absent or not numeric: "
            f"{contract.get('strike_price')!r}"
        ) from None
    if not math.isfinite(strike):
        raise ValueError(f"{symbol}: strike_price is not finite")

    expiry = contract.get("expiration_date")
    if not isinstance(expiry, str) or not _EXPIRY.match(expiry):
        raise ValueError(f"{symbol}: expiration_date must be YYYY-MM-DD, got {expiry!r}")

    return symbol, option_type, strike, expiry


# ---------------------------------------------------------------------------
# The four data-quality predicates
# ---------------------------------------------------------------------------

def _is_number(value):
    """True for a real, finite number. Bools are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _greeks_complete(snapshot, required):
    """Null greeks are `null`, not zero and not absent — never guess past them.

    A greek that is legitimately ~0 is fine; a greek that is None, absent, or
    not a finite number is not.
    """
    greeks = snapshot.get("greeks")
    if not isinstance(greeks, dict):
        return False
    return all(_is_number(greeks.get(name)) for name in required)


def _side_present(quote, price_key, size_key):
    """True only if one side of the quote is real and takeable.

    ``bp: 0, bs: 0`` (and its ``ap``/``as`` mirror) is how Alpaca says NO BID /
    NO ASK. Reading that zero as a $0.00 price is the bug these checks exist to
    prevent: it prices a spread off a side that does not exist.
    """
    if not isinstance(quote, dict):
        return False
    price = quote.get(price_key)
    size = quote.get(size_key)
    if not _is_number(price) or not _is_number(size):
        return False
    return price > 0 and size > 0


def _quote_age_seconds(quote, as_of):
    """Age of the quote in seconds, measured against `as_of`. None if unknowable."""
    if not isinstance(quote, dict):
        return None
    stamp = _parse_timestamp(quote.get("t"))
    if stamp is None:
        return None
    return (as_of - stamp).total_seconds()


def _parse_timestamp(value):
    """Parse an Alpaca RFC3339 timestamp, or None if it cannot be parsed."""
    if not isinstance(value, str):
        return None
    text = _SUBSECOND.sub(r".\1", value.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
