"""Shared loading and helpers for the GlassBox contract suites.

Four suites live here, built to the same pattern:

  GB-S  chain screener    — GB_INTERFACES.md shape 6
  GB-C  governor          — GB_INTERFACES.md shape 3 (+ 2, 2b, 3a)
  GB-L  provenance ledger — GB_INTERFACES.md shape 5 (+ 5a, and 4's id scheme)
  GB-D  data layer        — GB_INTERFACES.md shape 2b RAW, 6, 6c

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
from datetime import datetime, timedelta, timezone
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
_LEDGER_CANDIDATES = ("glassbox.ledger", "ledger")


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

LEDGER, LEDGER_MISSING_REASON = _import_module(_LEDGER_CANDIDATES, "Ledger")
LEDGER_MISSING = LEDGER is None

requires_ledger = pytest.mark.xfail(
    LEDGER_MISSING,
    reason=f"provenance ledger has not landed yet: {LEDGER_MISSING_REASON}",
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


#: The SCORED-RUN governor config, under config/ rather than under fixtures/.
#: The suite reads it because the scored bound is a DECIDED value that a test
#: must be able to fail on — a config nothing asserts against is a config that
#: can drift to anything between now and Thursday.
CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture(scope="session")
def scored_thresholds():
    with (CONFIG_DIR / "thresholds.governor.SCORED.json").open() as fh:
        return json.load(fh)


#: The SCORED-RUN config the competition account actually traded under. Read for
#: the same reason `scored_thresholds` is: the churn case below is a REAL pair of
#: decisions made under this exact file, and replaying them under the suite's
#: synthetic thresholds would be replaying a different day.
@pytest.fixture(scope="session")
def competition_thresholds():
    with (CONFIG_DIR / "thresholds.competition.json").open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def churn_case_entries():
    """2026-09-02's competition ledger, verbatim: the case the fix is about.

    Two governed orders on SPY, 55 seconds apart, both approved, both filled.
    The second was approvable only because the first had already FILLED and so
    was invisible to `churn_guard` — the composed view answered "when did we
    last open on SPY?" over the chains still in flight. This file is a byte copy
    of `demo/ledger_competition_sample.jsonl`; it is evidence, not a staged
    fixture, and GB-C-F09 asserts it is still the thing it claims to be.
    """
    path = GOV_FIXTURES / "ledger_churn_case.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def raw_of(composed):
    """The 2b RAW subset of a recorded composed view.

    `compose_account_view` passes `as_of`, `cash`, `buying_power` and
    `positions[].shares` straight through, so the raw state a recorded view was
    built from can be recovered from the view itself — which is what lets the
    suite re-compose a REAL decision's inputs without a broker.
    """
    return {
        "as_of": composed["as_of"],
        "cash": composed["cash"],
        "buying_power": composed["buying_power"],
        "positions": {symbol: {"shares": position["shares"]}
                      for symbol, position in composed["positions"].items()},
    }


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


# ---------------------------------------------------------------------------
# GB-L — provenance ledger
# ---------------------------------------------------------------------------

LEDGER_FIXTURES = FIXTURES / "ledger"

#: Shape 5's field order, with `corrects` (PROPOSED) seated next to `root_id`.
#: This IS the canonical serialization order; entries.jsonl is written in it.
ENTRY_FIELDS = (
    "id", "root_id", "corrects", "ts", "as_of", "mode", "status",
    "config_version", "prompt_version", "code_version",
    "approved_by", "approved_at", "snapshot", "proposal", "verdict",
    "order", "fill",
)

#: The seam's shape 5 status vocabulary, plus the one PROPOSED addition the root
#: decision entry needs (5a writes it pre-submission). Adding a value is a seam
#: change; this tuple is what the suite holds the module to.
SEAM_STATUSES = (
    "governor_rejected", "submitted", "broker_rejected", "filled",
    "partial_fill", "expired", "canceled",
)
PROPOSED_STATUSES = ("approved_pending",)

#: Root entries carry the decision; follow-ups carry the transition.
ROOT_ONLY_FIELDS = ("snapshot", "proposal", "verdict")


@pytest.fixture(scope="session")
def ledger_path():
    return LEDGER_FIXTURES / "entries.jsonl"


@pytest.fixture(scope="session")
def ledger_lines(ledger_path):
    """The golden file's raw lines — the serialization is part of the contract."""
    return ledger_path.read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="session")
def entries(ledger_lines):
    return [json.loads(line) for line in ledger_lines]


@pytest.fixture(scope="session")
def expected_chains():
    with (LEDGER_FIXTURES / "expected_chains.json").open() as fh:
        return json.load(fh)


@pytest.fixture()
def entry_by_id(entries):
    return {entry["id"]: entry for entry in entries}


def roots_of(entries):
    return [entry for entry in entries if entry["root_id"] is None]


def chain_of(entries, root_id):
    """The append-ordered chain for a root, folded the way the dashboard must.

    Independent of the module under test, and deliberately NOT contiguity-based:
    the golden file interleaves chains.
    """
    return [e for e in entries if (e["root_id"] or e["id"]) == root_id]


# ---------------------------------------------------------------------------
# GB-D — data layer
# ---------------------------------------------------------------------------

DF_FIXTURES = FIXTURES / "datafeed"

_DATAFEED_CANDIDATES = ("glassbox.datafeed", "datafeed")

DATAFEED, DATAFEED_MISSING_REASON = _import_module(_DATAFEED_CANDIDATES, "DataFeed")
DATAFEED_MISSING = DATAFEED is None

requires_datafeed = pytest.mark.xfail(
    DATAFEED_MISSING,
    reason=f"data layer has not landed yet: {DATAFEED_MISSING_REASON}",
    strict=True,
)

#: Shape 2b RAW — the data layer's whole output vocabulary. Anything else in an
#: account state it emits is a seam violation, and `reserved_*` in particular is
#: the governor's to derive from the ledger (A2 b).
RAW_ACCOUNT_FIELDS = ("as_of", "cash", "buying_power", "positions")


def _load_df(name):
    with (DF_FIXTURES / name).open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def df_contracts_pages():
    """The two recorded /v2/options/contracts pages, in order."""
    return [_load_df("contracts_page1.json"), _load_df("contracts_page2.json")]


@pytest.fixture(scope="session")
def df_snapshots_body():
    return _load_df("snapshots_indicative.json")


@pytest.fixture(scope="session")
def df_account():
    return _load_df("account.json")


@pytest.fixture(scope="session")
def df_positions():
    return _load_df("positions.json")


@pytest.fixture(scope="session")
def df_positions_mixed():
    """HAND-authored: the dev account is flat, so no recording shows this."""
    return _load_df("positions_mixed.HAND.json")


#: /v2/clock reports ONE state at a moment, so the open half of the pair can only
#: be recorded while the market is open. Until it is, the two tests that need it
#: are strict-xfail on its ABSENCE and arm themselves the instant the recorded
#: file appears — the same pattern as the module probes above, and for the same
#: reason: a fixture that was written rather than recorded would make this suite
#: pass against data no venue ever sent.
CLOCK_OPEN_FIXTURE = DF_FIXTURES / "clock_open.json"
CLOCK_OPEN_MISSING = not CLOCK_OPEN_FIXTURE.exists()

requires_clock_open = pytest.mark.xfail(
    CLOCK_OPEN_MISSING,
    reason="the OPEN /v2/clock has not been recorded yet: run "
           "`python scripts/record_fixtures.py --only clock` while the market is "
           "open. Nothing is derived from the closed clock",
    strict=True,
)


@pytest.fixture(scope="session")
def df_clock_open():
    """The recorded OPEN clock, or None until it has been recorded.

    Returning None rather than raising is deliberate: a fixture that raises
    during setup is an ERROR, and an error cannot be an expected failure. This
    way the dependent tests fail in their own call phase, `requires_clock_open`
    converts that to a strict xfail, and the day the file lands they arm with no
    edit to any assertion.
    """
    return _load_df("clock_open.json") if not CLOCK_OPEN_MISSING else None


@pytest.fixture(scope="session")
def df_clock_closed():
    return _load_df("clock_closed.json")


@pytest.fixture(scope="session")
def df_calendar():
    return _load_df("calendar.json")


@pytest.fixture(scope="session")
def df_calendar_halfday():
    """HAND-authored: Thanksgiving 2026 — an omitted holiday and a 13:00 close."""
    return _load_df("calendar_halfday.HAND.json")


#: A config that passes the paper guard. Credential-shaped, credential-free:
#: these are obvious non-secrets, and no test ever needs a real key.
FAKE_CONFIG = {
    "api_key": "RECORDED-NOT-A-KEY",
    "secret_key": "RECORDED-NOT-A-SECRET",
    "trading_base_url": "https://paper-api.alpaca.markets",
    "data_base_url": "https://data.alpaca.markets",
}


class RecordedResponse:
    """The slice of a requests.Response the data layer is allowed to use."""

    def __init__(self, status_code, body, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is NOT_JSON:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._body


NOT_JSON = object()


class RecordedSession:
    """A transport backed by recorded bodies. It has no network in it at all.

    Routes are keyed by URL path; a route is either a body or a callable taking
    the query params, which is how the two recorded contracts pages are served
    to a caller following `next_page_token`.

    Every request is recorded — path, params, and the NAMES of the headers sent,
    never their values — so a test can assert that auth was sent without a secret
    ever entering the suite.
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.split("://", 1)[-1].partition("/")[2]
        path = "/" + path
        self.requests.append({
            "url": url,
            "path": path,
            "params": dict(params or {}),
            "timeout": timeout,
            "header_names": sorted(headers or {}),
        })
        assert "/orders" not in path, (
            f"a GB-D test asked for {path!r}. Nothing in the data layer may touch "
            f"an orders endpoint: the data layer reads, and the executor — which "
            f"does not exist yet — is the only thing that writes"
        )
        if path not in self.routes:
            raise AssertionError(
                f"RecordedSession has no recorded body for {path!r}. A GB-D test "
                f"that wants one records it; it never falls through to a network"
            )
        route = self.routes[path]
        body = route(dict(params or {})) if callable(route) else route
        if isinstance(body, RecordedResponse):
            return body
        return RecordedResponse(200, body)

    def paths(self):
        return [request["path"] for request in self.requests]


def paged_contracts(pages):
    """Serve recorded contracts pages the way the endpoint does: by page_token."""
    def route(params):
        token = params.get("page_token")
        if token is None:
            return pages[0]
        for page in pages:
            if page.get("next_page_token") == token:
                index = pages.index(page) + 1
                if index < len(pages):
                    return pages[index]
        raise AssertionError(f"unknown page_token {token!r}")
    return route


# ---------------------------------------------------------------------------
# The live band — opt-in only
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run the @pytest.mark.live smoke test against the DEV paper account "
             "(reads only; never submits an order). Skipped by default.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: touches the DEV paper account over the network. Skipped unless "
        "--live is passed. Read-only, always.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live band: pass --live to run it (read-only)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# GB-E — executor
# ---------------------------------------------------------------------------

EXEC_FIXTURES = FIXTURES / "executor"

_EXECUTOR_CANDIDATES = ("glassbox.executor", "executor")

EXECUTOR, EXECUTOR_MISSING_REASON = _import_module(_EXECUTOR_CANDIDATES, "Executor")
EXECUTOR_MISSING = EXECUTOR is None

requires_executor = pytest.mark.xfail(
    EXECUTOR_MISSING,
    reason=f"executor has not landed yet: {EXECUTOR_MISSING_REASON}",
    strict=True,
)

#: Seam 4b, opening-only for this event. `buy_to_close` / `sell_to_close` are
#: RESERVED vocabulary and this pipeline never emits them.
POSITION_INTENTS = {"buy": "buy_to_open", "sell": "sell_to_open"}
CLOSING_INTENTS = ("buy_to_close", "sell_to_close")


@pytest.fixture(scope="session")
def broker_responses():
    with (EXEC_FIXTURES / "broker_responses.HAND.json").open() as fh:
        return json.load(fh)


class FakeTransport:
    """A broker that never existed.

    Records every submission verbatim and serves canned bodies built to Alpaca's
    order shape. It is the only transport GB-E has: no test in this suite can
    reach a venue, and the executor's own code path is identical either way,
    because the real transport implements the same two methods.
    """

    def __init__(self, responses, status="accepted"):
        self.responses = responses
        self.status = status
        self.submitted = []          # payloads, in submission order
        self.lookups = []            # client_order_ids asked about
        self.orders = {}             # client_order_id -> broker order record

    def submit_order(self, payload):
        self.submitted.append(json.loads(json.dumps(payload)))
        client_order_id = payload["client_order_id"]
        if client_order_id in self.orders:
            # What Alpaca does with a repeated client_order_id, and the whole
            # reason the id is derived from the ledger root (shape 4).
            from glassbox.executor import DuplicateOrder

            raise DuplicateOrder(client_order_id)
        self.orders[client_order_id] = self._body(payload, self.status)
        return self.orders[client_order_id]

    def get_order_by_client_id(self, client_order_id):
        self.lookups.append(client_order_id)
        return self.orders.get(client_order_id)

    # -- helpers for tests -------------------------------------------------

    def seed(self, client_order_id, status):
        """Pretend an order already exists at the broker under this id."""
        body = json.loads(json.dumps(self.responses[status]))
        body["client_order_id"] = client_order_id
        self.orders[client_order_id] = body
        return body

    def _body(self, payload, status):
        body = json.loads(json.dumps(self.responses[status]))
        body["client_order_id"] = payload["client_order_id"]
        body["qty"] = str(payload["qty"])
        body["limit_price"] = str(payload["limit_price"])
        body["order_class"] = payload.get("order_class", "")
        return body


class RefusingTransport:
    """A transport that fails the test if it is ever reached.

    Used where the executor must stop BEFORE the wire — an unapproved verdict, a
    missing order-id prefix, a non-paper URL. "It raised" is a weaker claim than
    "it raised and nothing was sent".
    """

    def __init__(self):
        self.submitted = []

    def submit_order(self, payload):
        raise AssertionError(
            f"the executor reached the wire when it must not have: {payload!r}"
        )

    def get_order_by_client_id(self, client_order_id):
        raise AssertionError("the executor reached the wire when it must not have")


@pytest.fixture()
def approved_roots(entries):
    """The GB-L golden ROOT entries that carry an approved verdict.

    Reused deliberately rather than re-authored: these are real decisions made by
    the real governor and already cross-checked against the GB-C golden checks
    map. The executor's input is a root ledger entry, so the ledger's goldens are
    exactly the right fixtures, and a proposal that GB-C says is approvable is
    the only kind the executor should ever see.
    """
    return {
        entry["proposal"]["structure"]: entry
        for entry in entries
        if entry["root_id"] is None and entry["verdict"]["approved"]
    }


@pytest.fixture()
def rejected_root(entries):
    for entry in entries:
        if entry["root_id"] is None and not entry["verdict"]["approved"]:
            return entry
    raise AssertionError("the ledger goldens carry no rejected root")


# ---------------------------------------------------------------------------
# GB-R — the session runner
#
# The runner is the only component with a loop in it, and the only one that
# decides to act more than once. Everything it drives is already under contract,
# so GB-R is not about screening or governing — it is about what an UNATTENDED
# process does: when it declines to act, when it stops, what it writes down, and
# whether running the same cycle twice opens two positions.
#
# It reaches no network. The venue below serves a hand-built chain with a known
# answer, and the broker below records every submission and never existed.
# ---------------------------------------------------------------------------

RUNNER_FIXTURES = FIXTURES / "runner"

_RUNNER_CANDIDATES = ("run_cycle",)
_SESSION_CANDIDATES = ("run_session",)

RUNNER, RUNNER_MISSING_REASON = _import_module(_RUNNER_CANDIDATES, "run_cycle")
RUNNER_MISSING = RUNNER is None

SESSION, SESSION_MISSING_REASON = _import_module(_SESSION_CANDIDATES, "run_session")
SESSION_MISSING = SESSION is None

requires_runner = pytest.mark.xfail(
    RUNNER_MISSING,
    reason=f"the cycle runner has not landed yet: {RUNNER_MISSING_REASON}",
    strict=True,
)

requires_session = pytest.mark.xfail(
    SESSION_MISSING,
    reason=f"the session loop has not landed yet: {SESSION_MISSING_REASON}",
    strict=True,
)


@pytest.fixture(scope="session")
def runner_chain():
    with (RUNNER_FIXTURES / "chain.json").open() as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def runner_config():
    with (CONFIG_DIR / "runner.PROPOSED.json").open() as fh:
        return json.load(fh)


def occ_symbol(underlying, expiry, option_type, strike):
    """The OCC symbol for a contract, built the way the venue writes it."""
    year, month, day = expiry.split("-")
    return (f"{underlying}{year[2:]}{month}{day}"
            f"{'C' if option_type == 'call' else 'P'}{int(round(strike * 1000)):08d}")


class FakeVenue:
    """Alpaca, as far as the data layer can tell. There is no network in it.

    Serves `/v2/clock`, `/v2/calendar`, `/v2/options/contracts`,
    `/v1beta1/options/snapshots`, `/v2/account` and `/v2/positions` from the
    hand-built chain fixture, and refuses `/orders` outright — the data path may
    not submit, and a fake that would let it is not a fake of this system.

    **Quote timestamps are stamped relative to `as_of`**, not baked into the
    fixture: `quote_max_age_seconds` is 300, so a fixture carrying fixed
    timestamps would go stale against its own suite the moment the reference
    date moved. `quote_age_seconds` is how far behind `as_of` they sit, and a
    test that wants `stale_quote` sets it past the threshold.
    """

    def __init__(self, chain, *, as_of, is_open=True, quote_age_seconds=30,
                 account=None):
        self.chain = chain
        self.as_of = as_of
        self.is_open = is_open
        self.quote_age_seconds = quote_age_seconds
        self.account = dict(account or chain["account"])
        self.requests = []

    # -- the wire ----------------------------------------------------------

    def get(self, url, headers=None, params=None, timeout=None):
        path = "/" + url.split("://", 1)[-1].partition("/")[2]
        assert "/orders" not in path, (
            f"the data path asked for {path!r}. Nothing in the data layer may "
            f"reach an orders endpoint; the executor holds its own transport"
        )
        self.requests.append({"path": path, "params": dict(params or {})})
        route = getattr(self, "_route_" + path.strip("/").replace("/", "_").replace("v1beta1", "beta"), None)
        if route is None:
            raise AssertionError(f"FakeVenue has no route for {path!r}")
        return RecordedResponse(200, route(dict(params or {})))

    # -- routes ------------------------------------------------------------

    def _route_v2_clock(self, params):
        stamp = self.as_of.isoformat().replace("+00:00", "Z")
        return {"timestamp": stamp, "is_open": self.is_open,
                "next_open": "2026-09-03T09:30:00-04:00",
                "next_close": "2026-09-02T16:00:00-04:00"}

    def _route_v2_calendar(self, params):
        # Two real sessions, so a CLOSED clock has a last close to resolve
        # against rather than the run raising (6c).
        return [{"date": "2026-09-01", "open": "09:30", "close": "16:00"},
                {"date": "2026-09-02", "open": "09:30", "close": "16:00"}]

    def _route_v2_options_contracts(self, params):
        gte, lte = params.get("expiration_date_gte"), params.get("expiration_date_lte")
        expiry = self.chain["expiry"]
        contracts = []
        if (gte is None or gte <= expiry) and (lte is None or expiry <= lte):
            for spec in self.chain["contracts"]:
                contracts.append({
                    "symbol": self.symbol_of(spec),
                    "underlying_symbol": self.chain["underlying"],
                    "type": spec["type"],
                    "strike_price": f"{spec['strike']}",
                    "expiration_date": expiry,
                    "open_interest": str(spec["open_interest"]),
                    "status": "active", "tradable": True, "multiplier": "100",
                })
        return {"option_contracts": contracts, "next_page_token": None}

    def _route_beta_options_snapshots(self, params):
        asked = set((params.get("symbols") or "").split(","))
        stamp = (self.as_of - timedelta(seconds=self.quote_age_seconds))
        quoted = stamp.isoformat().replace("+00:00", "Z")
        snapshots = {}
        for spec in self.chain["contracts"]:
            symbol = self.symbol_of(spec)
            if symbol not in asked:
                continue
            snapshots[symbol] = {
                "greeks": dict(self.chain["greeks_filler"], delta=spec["delta"]),
                "latestQuote": {"bp": spec["bid"], "bs": self.chain["bid_size"],
                                "ap": spec["ask"], "as": self.chain["ask_size"],
                                "t": quoted},
            }
        return {"snapshots": snapshots, "next_page_token": None}

    def _route_v2_account(self, params):
        return {"id": "b0000000-0000-4000-8000-00000000cafe",
                "account_number": self.account["account_number"],
                "status": self.account["status"],
                "cash": f"{self.account['cash']:.2f}",
                "equity": f"{self.account['equity']:.2f}",
                "buying_power": f"{self.account['buying_power']:.2f}"}

    def _route_v2_positions(self, params):
        # Empty on purpose: this account holds no equities, and an option
        # position is a contract, not a share (2b RAW).
        return []

    # -- helpers -----------------------------------------------------------

    def symbol_of(self, spec):
        return occ_symbol(self.chain["underlying"], self.chain["expiry"],
                          spec["type"], spec["strike"])


class FakeBroker(FakeTransport):
    """A broker that never existed, which also answers `/v2/account`.

    `statuses` is the sequence of Alpaca statuses a submitted order walks
    through as it is polled — `["accepted", "filled"]` is the ordinary life of a
    marketable limit order, and `["accepted"]` is one that simply never fills,
    which is a fact about the market and not a failure.
    """

    def __init__(self, responses, account, statuses=("accepted", "filled")):
        super().__init__(responses, status=statuses[0])
        self.account = account
        self.account_reads = 0
        self.statuses = list(statuses)
        self.progress = {}

    def get_account(self):
        self.account_reads += 1
        return self.account

    def get_order_by_client_id(self, client_order_id):
        self.lookups.append(client_order_id)
        if client_order_id not in self.orders:
            return None
        step = self.progress.get(client_order_id, 0)
        step = min(step + 1, len(self.statuses) - 1)
        self.progress[client_order_id] = step
        body = json.loads(json.dumps(self.responses[self.statuses[step]]))
        body["client_order_id"] = client_order_id
        self.orders[client_order_id] = body
        return body


class BlindBroker(FakeBroker):
    """A broker that cannot say who it is. 'I could not check' is not 'it is fine'."""

    def get_account(self):
        self.account_reads += 1
        raise RuntimeError("the account endpoint is unavailable")
