"""Shared loading + the PROPOSED screener seam for the chain-screener contract suite.

The screener module has not landed yet. Everything here is written so that the
suite COLLECTS and RUNS today: fixture-integrity criteria pass now, screener
behaviour criteria xfail until the module exists.

SIGNED INTERFACE — GB_INTERFACES.md shape 6.
This contract was proposed here pre-sign-off; it was lifted into the seam and
GB_INTERFACES.md is IN FORCE as of 2026-09-02. The seam is the authority: the
text below restates shape 6 and must not drift from it. Accepted entries are
shaped to drop straight into shape 2 `legs[]`
(`symbol` / `option_type` / `strike` / `expiry`).

    screen_chain(contracts, snapshots, as_of, thresholds) -> result

      contracts  : the parsed /v2/options/contracts body (dict with
                   "option_contracts": [...])
      snapshots  : the parsed /v1beta1/options/snapshots body (dict with
                   "snapshots": {symbol: {...}})
      as_of      : timezone-aware datetime the freshness check is measured against
      thresholds : mapping of tunables (see fixtures/thresholds.PROPOSED.json)

      result     : mapping or object exposing
                     .accepted -> [{symbol, option_type, strike, expiry}, ...]
                     .rejected -> [{symbol, reasons: [code, ...]}, ...]
                   Every input contract appears in exactly one of the two lists.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Candidate import paths, in preference order. The module author picks one; the
# suite does not care which, and this list is the only thing that needs editing.
_SCREENER_CANDIDATES = ("glassbox.screener", "screener")


def _import_screener():
    """Return (module, None) once the screener lands, else (None, reason)."""
    tried = []
    for path in _SCREENER_CANDIDATES:
        try:
            mod = __import__(path, fromlist=["screen_chain"])
        except ImportError:
            tried.append(path)
            continue
        if not hasattr(mod, "screen_chain"):
            return None, f"{path} imported but exposes no screen_chain()"
        return mod, None
    return None, "no screener module found (tried: " + ", ".join(tried) + ")"


SCREENER, SCREENER_MISSING_REASON = _import_screener()
SCREENER_MISSING = SCREENER is None

#: Attach to any test that exercises the screener itself. Once the module lands
#: the condition goes False, the marker deactivates, and the test runs for real.
#: strict=True so a test that "passes" without a screener is reported as a
#: failure rather than quietly counting as coverage.
requires_screener = pytest.mark.xfail(
    SCREENER_MISSING,
    reason=f"chain screener has not landed yet: {SCREENER_MISSING_REASON}",
    strict=True,
)


def _load(name):
    with (FIXTURES / name).open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def contracts_body():
    return _load("contracts_spy_2026-09-18.json")


@pytest.fixture(scope="session")
def snapshots_body():
    return _load("snapshots_spy_2026-09-18.json")


@pytest.fixture(scope="session")
def thresholds():
    return _load("thresholds.PROPOSED.json")


@pytest.fixture(scope="session")
def golden():
    return _load("expected_verdicts.json")


@pytest.fixture(scope="session")
def as_of(golden):
    return parse_ts(golden["as_of"])


@pytest.fixture(scope="session")
def contracts(contracts_body):
    return contracts_body["option_contracts"]


@pytest.fixture(scope="session")
def snapshots(snapshots_body):
    return snapshots_body["snapshots"]


def parse_ts(value):
    """Parse an Alpaca RFC3339 timestamp, truncating ns -> us for datetime."""
    text = value.replace("Z", "+00:00")
    text = re.sub(r"\.(\d{6})\d+", r".\1", text)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def quote_age_seconds(snapshot, as_of_dt):
    return (as_of_dt - parse_ts(snapshot["latestQuote"]["t"])).total_seconds()


def has_bid(snapshot):
    """True only if a real, takeable bid exists.

    bp == 0 / bs == 0 is Alpaca's representation of NO BID, not a $0.00 price.
    """
    quote = snapshot.get("latestQuote")
    if not quote:
        return False
    bid_price = quote.get("bp")
    bid_size = quote.get("bs")
    if bid_price is None or bid_size is None:
        return False
    return bid_price > 0 and bid_size > 0


def has_ask(snapshot):
    """True only if a real, takeable ask exists.

    The mirror of has_bid: ap == 0 / as == 0 is Alpaca's representation of NO
    ASK. It matters on its own because a vertical BUYS a leg — a missing ask is
    un-executable on the long side (GB_INTERFACES.md shape 6, `missing_ask`).
    """
    quote = snapshot.get("latestQuote")
    if not quote:
        return False
    ask_price = quote.get("ap")
    ask_size = quote.get("as")
    if ask_price is None or ask_size is None:
        return False
    return ask_price > 0 and ask_size > 0


def has_complete_greeks(snapshot, required):
    greeks = snapshot.get("greeks")
    if not isinstance(greeks, dict):
        return False
    return all(greeks.get(name) is not None for name in required)


def run_screener(contracts_body, snapshots_body, as_of_dt, thresholds_map):
    """Call the PROPOSED seam and normalise the result to (accepted, rejected)."""
    result = SCREENER.screen_chain(
        contracts_body, snapshots_body, as_of=as_of_dt, thresholds=thresholds_map
    )
    if isinstance(result, dict):
        accepted, rejected = result.get("accepted"), result.get("rejected")
    else:
        accepted, rejected = getattr(result, "accepted", None), getattr(
            result, "rejected", None
        )
    assert accepted is not None and rejected is not None, (
        "screen_chain() must expose 'accepted' and 'rejected' "
        "(mapping keys or attributes) per the PROPOSED interface in conftest.py"
    )
    return list(accepted), list(rejected)


def symbols_of(entries):
    return {e["symbol"] if isinstance(e, dict) else e.symbol for e in entries}


def reasons_for(rejected, symbol):
    for entry in rejected:
        sym = entry["symbol"] if isinstance(entry, dict) else entry.symbol
        if sym == symbol:
            raw = entry["reasons"] if isinstance(entry, dict) else entry.reasons
            return set(raw)
    return None
