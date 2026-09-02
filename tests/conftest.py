"""Shared loading and helpers for the GlassBox contract suites.

Two suites live here, built to the same pattern:

  GB-S  chain screener   — GB_INTERFACES.md shape 6
  GB-C  governor         — GB_INTERFACES.md shape 3 (+ 2, 2b, 3a)

Each suite has a fixture-integrity band that runs today and guards the golden
data, and a behaviour band that is strict-xfail until its module lands and then
arms itself automatically. Nothing here reaches for a module that does not exist
yet, so the suites always COLLECT and RUN.

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

#: OCC contract symbol, e.g. SPY260918C00640000. One definition, both suites:
#: a second copy is a second thing to drift.
OCC = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
                 r"(?P<cp>[CP])(?P<strike>\d{8})$")

# Candidate import paths, in preference order. The module author picks one; the
# suite does not care which, and these lists are the only thing that needs editing.
_SCREENER_CANDIDATES = ("glassbox.screener", "screener")
_GOVERNOR_CANDIDATES = ("glassbox.governor", "governor")


def _import_module(candidates, entry_point):
    """Return (module, None) once the module lands, else (None, reason)."""
    tried = []
    for path in candidates:
        try:
            mod = __import__(path, fromlist=[entry_point])
        except ImportError:
            tried.append(path)
            continue
        if not hasattr(mod, entry_point):
            return None, f"{path} imported but exposes no {entry_point}()"
        return mod, None
    return None, "not found (tried: " + ", ".join(tried) + ")"


SCREENER, SCREENER_MISSING_REASON = _import_module(_SCREENER_CANDIDATES, "screen_chain")
SCREENER_MISSING = SCREENER is None

GOVERNOR, GOVERNOR_MISSING_REASON = _import_module(_GOVERNOR_CANDIDATES, "govern")
GOVERNOR_MISSING = GOVERNOR is None

#: Attach to any test that exercises the module itself. Once it lands the
#: condition goes False, the marker deactivates, and the test runs for real.
#: strict=True so a test that "passes" without the module is reported as a
#: failure rather than quietly counting as coverage.
requires_screener = pytest.mark.xfail(
    SCREENER_MISSING,
    reason=f"chain screener has not landed yet: {SCREENER_MISSING_REASON}",
    strict=True,
)

requires_governor = pytest.mark.xfail(
    GOVERNOR_MISSING,
    reason=f"governor has not landed yet: {GOVERNOR_MISSING_REASON}",
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


# ---------------------------------------------------------------------------
# GB-C — governor
# ---------------------------------------------------------------------------

GOV_FIXTURES = FIXTURES / "governor"

#: The pinned core checks[] vocabulary, GB_INTERFACES.md 3a. Renaming or removing
#: one of these is a seam change; extras ride an x_ prefix.
CORE_RULES = (
    "structure_valid",
    "net_reconciles",
    "max_loss_cap",
    "coverage",
    "cash_floor",
    "churn_guard",
    "market_open",
)


def _load_gov(name):
    with (GOV_FIXTURES / name).open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def gov_thresholds():
    return _load_gov("thresholds.governor.PROPOSED.json")


@pytest.fixture(scope="session")
def proposals():
    return _load_gov("proposals.json")["proposals"]


@pytest.fixture(scope="session")
def account_states():
    return _load_gov("account_states.json")["account_states"]


@pytest.fixture(scope="session")
def clocks():
    return _load_gov("clocks.json")["clocks"]


@pytest.fixture(scope="session")
def gov_golden():
    return _load_gov("expected_verdicts.json")


@pytest.fixture(scope="session")
def gov_config_version(gov_golden):
    return gov_golden["config_version"]


def run_governor(proposal, account_state, clock, thresholds, mode, config_version):
    """Call the seam shape 3 entry point and sanity-check the envelope."""
    verdict = GOVERNOR.govern(
        proposal,
        account_state,
        clock,
        thresholds=thresholds,
        mode=mode,
        config_version=config_version,
    )
    assert isinstance(verdict, dict), "the verdict is a mapping per seam shape 3"
    for key in ("approved", "mode", "config_version", "checks", "reason"):
        assert key in verdict, f"verdict missing {key} (seam shape 3)"
    return verdict


def run_case(case, proposals_map, accounts_map, clocks_map, thresholds, config_version):
    """Run one golden case by name-references, exactly as the golden file states it."""
    return run_governor(
        proposals_map[case["proposal"]],
        accounts_map[case["account"]],
        clocks_map[case["clock"]],
        thresholds,
        case["mode"],
        config_version,
    )


def checks_map(verdict):
    """{rule: passed} — asserts rules are unique, since a duplicate hides a verdict."""
    rules = [c["rule"] for c in verdict["checks"]]
    assert len(rules) == len(set(rules)), f"duplicate rule in checks[]: {rules}"
    return {c["rule"]: c["passed"] for c in verdict["checks"]}


def detail_for(verdict, rule):
    for check in verdict["checks"]:
        if check["rule"] == rule:
            return check["detail"]
    return None


def detail_fields(detail):
    """Parse the seam's `k=v` detail convention into a mapping.

    Shape 3's own example is `computed_max_loss=250.00 vs cap=500.00`: key=value
    tokens with prose between them. Bare words are ignored so the detail stays
    readable to a human and parseable by the dashboard and this suite.
    """
    fields = {}
    for token in (detail or "").split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


def money(value):
    """Parse a money field out of a detail string."""
    return None if value is None or value == "null" else float(value)


def net_from_legs(proposal):
    """The C1 reconciliation rule, reimplemented independently for the F-band.

    Per share, for ONE unit of the spread. `qty` is NOT a factor and must not
    appear in this sum.
    """
    total = 0.0
    for leg in proposal["legs"]:
        sign = 1 if leg["action"] == "buy" else -1
        total += sign * leg["limit_price"] * leg["ratio_qty"]
    return round(total, 6)
