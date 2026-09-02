"""GB-D — data-layer contract suite.

The acceptance gate for the data layer (CLAUDE.md: "a module merges when its
suite passes"). The data layer is I/O by nature, which is exactly why this suite
contains no I/O: **every test here runs against bodies recorded once from the DEV
paper account** (`scripts/record_fixtures.py`) and served through an injectable
transport. A suite that reached the network would be green when the venue is up
and red when it is not, and would say nothing about our code either way.

Two bands, plus one that is off:

  GB-D-F**    fixture integrity — runs today, guards the recorded data.
  GB-D-**     data-layer behaviour — xfail until the module lands, then runs for
              real automatically (see conftest.requires_datafeed).
  GB-D-live-* one read-only smoke test against the DEV account, marked
              `@pytest.mark.live` and SKIPPED unless --live is passed.

The interfaces under test are GB_INTERFACES.md **2b RAW** (the data layer's
output — raw broker state, no reservations), **shape 6** (the screener's input),
and **6c** (the caller's `as_of` policy). The seam is the authority.

Three properties this suite exists to pin, because each has a failure mode that
looks like thin data rather than like a bug:

1. `/v2/options/contracts` paginates **nearest-expiry-first**, so an unfiltered
   or early-terminated fetch quietly returns the front expiry.
2. The data layer emits **raw** account state and never a reservation (A2 b) —
   and the governor refuses raw state where its composed view belongs, so the
   rule is enforced from both ends.
3. `as_of` is **resolved from the venue's own clock and calendar** (6c), never
   from a hand-rolled market calendar and never from the wall clock.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone

import pytest

from conftest import (
    DATAFEED,
    DF_FIXTURES,
    FAKE_CONFIG,
    NOT_JSON,
    OCC,
    RAW_ACCOUNT_FIELDS,
    RecordedResponse,
    RecordedSession,
    paged_contracts,
    requires_clock_open,
    parse_ts,
    quote_age_seconds,
    requires_datafeed,
    run_screener,
)

UNDERLYING = "SPY"
WINDOW = {"expiration_date_gte": "2026-09-23", "expiration_date_lte": "2026-10-17"}

CONTRACTS_PATH = "/v2/options/contracts"
SNAPSHOTS_PATH = "/v1beta1/options/snapshots"
ACCOUNT_PATH = "/v2/account"
POSITIONS_PATH = "/v2/positions"
CLOCK_PATH = "/v2/clock"

#: The last close the recorded quotes were struck at — 2026-09-01 16:00 ET.
LAST_CLOSE = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)


def feed_with(routes):
    """A DataFeed over a RecordedSession. The only transport this suite has."""
    session = RecordedSession(routes)
    return DATAFEED.DataFeed(FAKE_CONFIG, session=session), session


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_d_f01_contracts_pages_match_the_wire(df_contracts_pages):
    """GB-D-F01: recorded contracts pages are /v2/options/contracts, verbatim."""
    page1, page2 = df_contracts_pages
    required = {
        "id", "symbol", "name", "status", "tradable", "expiration_date",
        "root_symbol", "underlying_symbol", "underlying_asset_id", "type",
        "style", "strike_price", "multiplier", "size", "open_interest",
        "close_price",
    }
    for page in df_contracts_pages:
        assert page["option_contracts"], "a recorded page must not be empty"
        for contract in page["option_contracts"]:
            missing = required - set(contract)
            assert not missing, f"{contract.get('symbol')} missing {sorted(missing)}"

            # Numerics are STRINGS on this endpoint (fixtures README trap 2).
            # open_interest / close_price are null on strikes that never traded,
            # which is a different fact from a missing key.
            assert isinstance(contract["strike_price"], str)
            for field in ("open_interest", "close_price"):
                assert contract[field] is None or isinstance(contract[field], str)

            match = OCC.match(contract["symbol"])
            assert match, f"{contract['symbol']} is not a valid OCC symbol"
            assert match["cp"] == contract["type"][0].upper()
            assert float(match["strike"]) / 1000 == float(contract["strike_price"])
            assert (
                f"20{match['yy']}-{match['mm']}-{match['dd']}"
                == contract["expiration_date"]
            )

    # The pagination sample is only a sample if the pages actually chain and
    # actually differ. A "two-page" fixture of one page twice proves nothing.
    assert page1["next_page_token"], "page 1 must carry a next_page_token"
    first = {c["symbol"] for c in page1["option_contracts"]}
    second = {c["symbol"] for c in page2["option_contracts"]}
    assert not (first & second), "the two recorded pages overlap"

    # The recorded run is COMPLETE: page 2 terminates. A "two-page" sample that
    # is really two pages of a longer run cannot prove a fetcher runs out.
    assert page2["next_page_token"] is None, (
        "page 2 must be the last page, or GB-D-02 proves nothing about termination"
    )

    # Nearest-expiry-first (trap 1), visible ACROSS the page boundary: the
    # expiries are non-decreasing through the merged run, and every expiry on
    # page 1 is at or before every expiry on page 2. This is why an unfiltered
    # or early-terminated fetch returns the front of the window and looks like a
    # healthy thin chain rather than like a bug.
    merged = page1["option_contracts"] + page2["option_contracts"]
    expiries = [c["expiration_date"] for c in merged]
    assert expiries == sorted(expiries), f"not nearest-expiry-first: {expiries}"
    assert max(c["expiration_date"] for c in page1["option_contracts"]) <= min(
        c["expiration_date"] for c in page2["option_contracts"]
    )
    assert len(set(expiries)) > 1, (
        "the sample should span the window, not sit inside one expiry"
    )


def test_gb_d_f02_snapshots_match_the_indicative_feed(df_snapshots_body,
                                                      df_contracts_pages):
    """GB-D-F02: snapshots are keyed by symbol, and greeks are null-or-complete."""
    snapshots = df_snapshots_body["snapshots"]
    recorded = {c["symbol"]
                for page in df_contracts_pages for c in page["option_contracts"]}
    assert set(snapshots) <= recorded, "a snapshot for a contract we did not record"

    null_greeks = 0
    for symbol, snapshot in snapshots.items():
        quote = snapshot.get("latestQuote")
        assert quote, f"{symbol} has no latestQuote"
        for field in ("ap", "as", "bp", "bs", "t"):
            assert field in quote, f"{symbol}.latestQuote missing {field}"
        # Numbers here, strings on the contracts endpoint (trap 2).
        assert isinstance(quote["ap"], (int, float))
        assert isinstance(quote["bp"], (int, float))
        parse_ts(quote["t"])

        greeks = snapshot.get("greeks")
        assert greeks is None or set(greeks) == {"delta", "gamma", "theta", "vega", "rho"}
        if greeks is None:
            null_greeks += 1
        else:
            assert all(v is not None for v in greeks.values()), (
                f"{symbol}: greeks are null or complete, never partial"
            )

    # This arrived in a real recording rather than being staged, and it is the
    # documented free-tier behaviour the screener must fail closed on.
    assert null_greeks >= 1, (
        "the recording should contain at least one deep-ITM null-greeks snapshot"
    )


def test_gb_d_f03_account_is_scrubbed_to_the_account_id(df_account, df_positions):
    """GB-D-F03: identity scrubbed, the account id deliberately kept."""
    assert "account_number" not in df_account, "account_number must be scrubbed"
    assert df_account.get("id"), (
        "the account id is KEPT on purpose: it is not a credential, the "
        "submission needs one, and a recording that cannot name its account is a "
        "recording of nothing"
    )
    for field in ("cash", "buying_power"):
        assert isinstance(df_account[field], str), (
            f"{field} is a STRING on the wire (trap 2); a fixture that pre-casts "
            f"it would hide the cast this module has to do"
        )
    assert isinstance(df_positions, list), "/v2/positions returns a list"


@requires_clock_open
def test_gb_d_f04_clock_pair_is_one_open_and_one_closed(df_clock_open,
                                                        df_clock_closed):
    """GB-D-F04: both clock states are recorded, and they are the same shape."""
    assert df_clock_open["is_open"] is True
    assert df_clock_closed["is_open"] is False
    assert set(df_clock_open) == set(df_clock_closed), (
        "the two clock recordings must be the same shape — if they are not, one "
        "of them was written rather than recorded"
    )
    for clock in (df_clock_open, df_clock_closed):
        for field in ("timestamp", "next_open", "next_close"):
            parse_ts(clock[field])


def test_gb_d_f05_calendar_covers_the_closed_clock(df_calendar, df_clock_closed):
    """GB-D-F05: the calendar window actually contains a session that has closed."""
    assert df_calendar, "the calendar recording must not be empty"
    dates = [session["date"] for session in df_calendar]
    assert dates == sorted(dates), "sessions come back in date order"
    for session in df_calendar:
        assert set(session) >= {"date", "open", "close"}
        datetime.strptime(session["date"], "%Y-%m-%d")
        assert session["close"].count(":") == 1, "close is local HH:MM"

    now = parse_ts(df_clock_closed["timestamp"])
    closed_before_now = [
        session for session in df_calendar
        if datetime.strptime(session["date"], "%Y-%m-%d").date() < now.date()
    ]
    assert closed_before_now, (
        "resolve_as_of has nothing to resolve against: the recorded calendar "
        "window contains no session that closed before the recorded clock"
    )


def test_gb_d_f06_no_credential_is_anywhere_in_the_fixtures():
    """GB-D-F06: the recorder's promise, checked rather than trusted.

    Compares against the live values when this box has them, and never prints,
    logs, or asserts on a secret's content.
    """
    secrets = [os.environ.get(name) for name in
               ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ANTHROPIC_API_KEY")]
    secrets = [s for s in secrets if s and len(s) >= 12]
    files = sorted(DF_FIXTURES.glob("*.json")) + sorted(DF_FIXTURES.glob("*.md"))
    assert files, "the GB-D fixture directory is empty"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for secret in secrets:
            assert secret not in text, (
                f"{path.name} contains a credential. Do not edit it out and move "
                f"on — work out how the recorder wrote it"
            )
        assert "APCA-API-SECRET-KEY" not in text, (
            f"{path.name} looks like it recorded request headers"
        )


def test_gb_d_f07_recorded_quotes_are_fresh_only_against_the_6c_as_of(
    df_snapshots_body, df_clock_closed, thresholds
):
    """GB-D-F07: trap 5 — the same quotes are fresh or stale by `as_of` alone.

    This is 6c's whole argument in one subtraction. The recording was made before
    the open, so against wall-clock-at-read-time every quote is hours old and the
    screener rejects the entire chain; against the last close it is measured from,
    every quote is a fraction of a second old.
    """
    budget = thresholds["quote_max_age_seconds"]
    wall_clock_now = parse_ts(df_clock_closed["timestamp"])
    for symbol, snapshot in df_snapshots_body["snapshots"].items():
        fresh = quote_age_seconds(snapshot, LAST_CLOSE)
        stale = quote_age_seconds(snapshot, wall_clock_now)
        assert 0 <= fresh <= budget, f"{symbol} is not fresh against the last close"
        assert stale > budget, f"{symbol} is not stale against the wall clock"


# ---------------------------------------------------------------------------
# GB-D-01..04 — the chain, and the pagination that is not optional
# ---------------------------------------------------------------------------

@requires_datafeed
def test_gb_d_01_contracts_fetch_filters_by_expiry_window(df_contracts_pages):
    """GB-D-01: the expiry filter and the underlying reach the wire."""
    feed, session = feed_with({CONTRACTS_PATH: paged_contracts(df_contracts_pages)})
    feed.fetch_contracts(UNDERLYING, as_of=LAST_CLOSE, **WINDOW)

    assert session.paths() == [CONTRACTS_PATH, CONTRACTS_PATH]
    first = session.requests[0]["params"]
    assert first["underlying_symbols"] == UNDERLYING
    assert first["expiration_date_gte"] == WINDOW["expiration_date_gte"]
    assert first["expiration_date_lte"] == WINDOW["expiration_date_lte"]
    # Page 2 keeps the filter AND carries the token; a re-request that dropped
    # the window would silently walk off the end of it.
    second = session.requests[1]["params"]
    assert second["page_token"] == df_contracts_pages[0]["next_page_token"]
    assert second["expiration_date_gte"] == WINDOW["expiration_date_gte"]


@requires_datafeed
def test_gb_d_02_contracts_fetch_follows_pagination_to_completion(df_contracts_pages):
    """GB-D-02: every page is followed, merged in order, and said to be finished."""
    feed, session = feed_with({CONTRACTS_PATH: paged_contracts(df_contracts_pages)})
    body = feed.fetch_contracts(UNDERLYING, as_of=LAST_CLOSE, **WINDOW)

    expected = (df_contracts_pages[0]["option_contracts"]
                + df_contracts_pages[1]["option_contracts"])
    assert body["option_contracts"] == expected, (
        "the merged body is every page, in page order"
    )
    assert body["pages"] == 2
    # An explicit null, not an absent key: the same discipline as shape 5's
    # nullable order/fill — it says the fetch ran out, rather than leaving a
    # reader unable to tell completion from truncation.
    assert "next_page_token" in body and body["next_page_token"] is None


@requires_datafeed
def test_gb_d_03_contracts_fetch_refuses_an_unfiltered_window(df_contracts_pages):
    """GB-D-03: no expiry window is an error, not a default.

    Nearest-expiry-first means an unfiltered fetch returns the front expiry and
    looks like a perfectly healthy thin chain. Failing closed is the only honest
    behaviour, and it must happen before a request goes out.
    """
    feed, session = feed_with({CONTRACTS_PATH: paged_contracts(df_contracts_pages)})
    with pytest.raises(ValueError, match="expiration_date"):
        feed.fetch_contracts(UNDERLYING, as_of=LAST_CLOSE,
                             expiration_date_gte=None, expiration_date_lte=None)
    assert session.requests == [], "it must raise BEFORE the request"


@requires_datafeed
def test_gb_d_04_a_repeating_page_token_raises_rather_than_looping(df_contracts_pages):
    """GB-D-04: a venue that keeps handing back the same token is a bug, not a wait."""
    stuck = dict(df_contracts_pages[0])
    stuck["next_page_token"] = "SAME-TOKEN-FOREVER"
    feed, session = feed_with({CONTRACTS_PATH: stuck})
    with pytest.raises(DATAFEED.DataFeedError, match="not terminating"):
        feed.fetch_contracts(UNDERLYING, as_of=LAST_CLOSE, **WINDOW)
    assert len(session.requests) < 10, "it must give up quickly, not spin"


# ---------------------------------------------------------------------------
# GB-D-05..06 — snapshots, in the exact form the screener consumes
# ---------------------------------------------------------------------------

@requires_datafeed
def test_gb_d_05_snapshots_drop_straight_into_the_screener(
    df_contracts_pages, df_snapshots_body, thresholds
):
    """GB-D-05: the data layer's two outputs ARE the screener's two inputs.

    Not "a compatible shape" — the actual bodies, passed unmodified into
    `screen_chain`, partitioning every contract into exactly one list (shape 6).
    This is the seam between the two modules, exercised rather than described.
    """
    symbols = [c["symbol"]
               for page in df_contracts_pages for c in page["option_contracts"]]
    feed, session = feed_with({
        CONTRACTS_PATH: paged_contracts(df_contracts_pages),
        SNAPSHOTS_PATH: df_snapshots_body,
    })
    contracts = feed.fetch_contracts(UNDERLYING, as_of=LAST_CLOSE, **WINDOW)
    snapshots = feed.fetch_snapshots(symbols, as_of=LAST_CLOSE)

    assert set(snapshots["snapshots"]) <= set(symbols)
    assert all(isinstance(body, dict) for body in snapshots["snapshots"].values())

    accepted, rejected = run_screener(contracts, snapshots, LAST_CLOSE, thresholds)
    assert len(accepted) + len(rejected) == len(symbols)
    assert {e["symbol"] for e in accepted} | {e["symbol"] for e in rejected} == set(symbols)
    # The recording carries real null greeks, so a real fail-closed rejection
    # comes out of the real chain rather than out of a staged fixture.
    assert any("null_greeks" in e["reasons"] for e in rejected)
    assert accepted, "the recorded chain should not screen to nothing"


@requires_datafeed
def test_gb_d_06_snapshots_chunk_and_merge(df_snapshots_body):
    """GB-D-06: more symbols than fit in one URL still come back as one mapping."""
    symbols = [f"SPY2609{25}C{strike:08d}" for strike in
               range(300_000, 300_000 + 250 * 1000, 1000)]
    assert len(symbols) == 250

    def route(params):
        asked = params["symbols"].split(",")
        assert len(asked) <= 100, "chunks must respect the URL-length bound"
        return {"snapshots": {symbol: {"latestQuote": {}} for symbol in asked},
                "next_page_token": None}

    feed, session = feed_with({SNAPSHOTS_PATH: route})
    body = feed.fetch_snapshots(symbols, as_of=LAST_CLOSE)

    assert len(session.requests) == 3, "250 symbols is three chunks, not one"
    assert set(body["snapshots"]) == set(symbols), "every chunk is merged in"
    assert body["next_page_token"] is None


# ---------------------------------------------------------------------------
# GB-D-07..10 — shape 2b RAW, and the A2(b) boundary
# ---------------------------------------------------------------------------

@requires_datafeed
def test_gb_d_07_raw_account_state_is_exactly_shape_2b_raw(df_account, df_positions):
    """GB-D-07: raw broker state, and NOT ONE reservation field (A2 b)."""
    feed, session = feed_with({ACCOUNT_PATH: df_account, POSITIONS_PATH: df_positions})
    state = feed.fetch_raw_account_state(as_of=LAST_CLOSE)

    assert set(state) == set(RAW_ACCOUNT_FIELDS), (
        f"2b RAW is exactly {RAW_ACCOUNT_FIELDS}; got {sorted(state)}"
    )
    assert "reserved_cash" not in state
    for position in state["positions"].values():
        assert set(position) == {"shares"}, "raw positions carry shares and nothing else"

    # Belt and braces: no reserved_* anywhere at any depth. The data layer is a
    # dumb, honest reporter; the component that owns risk owns "already spoken
    # for", and a reservation invented here would be a second source of truth
    # for the one number coverage turns on.
    assert "reserved" not in json.dumps(state)


@requires_datafeed
def test_gb_d_08_the_governor_refuses_the_raw_state(df_account, df_positions,
                                                    proposals, clocks,
                                                    gov_thresholds,
                                                    gov_config_version):
    """GB-D-08: A2(b) enforced from BOTH ends, in one test.

    GB-C-21 already proves the governor raises on raw state. This proves the
    thing it raises on is what the data layer actually emits — otherwise the two
    modules could each be right about a shape neither of them produces.
    """
    governor = pytest.importorskip("glassbox.governor")
    feed, _ = feed_with({ACCOUNT_PATH: df_account, POSITIONS_PATH: df_positions})
    raw = feed.fetch_raw_account_state(as_of=LAST_CLOSE)

    with pytest.raises(ValueError, match="reserved_cash"):
        governor.govern(
            next(iter(proposals.values())), raw, next(iter(clocks.values())),
            thresholds=gov_thresholds, mode="approve",
            config_version=gov_config_version,
        )


@requires_datafeed
def test_gb_d_09_only_equity_positions_become_shares(df_account, df_positions_mixed):
    """GB-D-09: a short call is a contract, never minus one share.

    The most dangerous single mistake this module could make: counting an option
    position as `shares` would make a naked short look covered by arithmetic, and
    the coverage check (2e) would agree with it.
    """
    feed, _ = feed_with({ACCOUNT_PATH: df_account, POSITIONS_PATH: df_positions_mixed})
    state = feed.fetch_raw_account_state(as_of=LAST_CLOSE)

    assert state["positions"] == {"SPY": {"shares": 100}, "AAPL": {"shares": 50}}
    assert "SPY260925C00780000" not in state["positions"], (
        "an option position must never appear as shares"
    )


@requires_datafeed
def test_gb_d_10_wire_strings_are_cast_and_a_bad_balance_raises(df_account,
                                                                df_positions):
    """GB-D-10: `"100000"` becomes a number; garbage becomes an exception."""
    feed, _ = feed_with({ACCOUNT_PATH: df_account, POSITIONS_PATH: df_positions})
    state = feed.fetch_raw_account_state(as_of=LAST_CLOSE)
    assert isinstance(state["cash"], float)
    assert isinstance(state["buying_power"], float)
    assert state["cash"] == float(df_account["cash"])

    broken = copy.deepcopy(df_account)
    broken["cash"] = "unavailable"
    feed, _ = feed_with({ACCOUNT_PATH: broken, POSITIONS_PATH: df_positions})
    with pytest.raises(DATAFEED.DataFeedError, match="not numeric"):
        feed.fetch_raw_account_state(as_of=LAST_CLOSE)


# ---------------------------------------------------------------------------
# GB-D-11..16 — 6c, the as_of policy
# ---------------------------------------------------------------------------

@requires_datafeed
@requires_clock_open
def test_gb_d_11_open_market_resolves_as_of_to_now(df_clock_open, df_calendar):
    """GB-D-11: market open -> `now`, exactly the value the caller injected."""
    now = datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc)
    assert DATAFEED.resolve_as_of(df_clock_open, df_calendar, now=now) == now


@requires_datafeed
def test_gb_d_12_closed_market_resolves_as_of_to_the_last_close(df_clock_closed,
                                                               df_calendar):
    """GB-D-12: market closed -> the last close, off /v2/calendar, in UTC."""
    now = DATAFEED.parse_wire_ts(df_clock_closed["timestamp"])
    resolved = DATAFEED.resolve_as_of(df_clock_closed, df_calendar, now=now)

    assert resolved == LAST_CLOSE, "2026-09-01 16:00 America/New_York, in UTC"
    assert resolved.tzinfo is not None and resolved != now


@requires_datafeed
def test_gb_d_13_resolve_as_of_reads_no_clock(df_clock_closed, df_calendar):
    """GB-D-13: the answer is a function of the arguments and nothing else.

    Two callers hours apart, same clock and calendar, same `as_of` — which is
    what makes a verdict re-checkable months later (shape 5's `as_of`).
    """
    first = DATAFEED.resolve_as_of(
        df_clock_closed, df_calendar,
        now=datetime(2026, 9, 2, 11, 39, tzinfo=timezone.utc),
    )
    second = DATAFEED.resolve_as_of(
        df_clock_closed, df_calendar,
        now=datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc),
    )
    assert first == second == LAST_CLOSE


@requires_datafeed
def test_gb_d_14_no_closed_session_in_the_window_raises(df_clock_closed, df_calendar):
    """GB-D-14: fail closed. A guessed `as_of` is worse than no `as_of`."""
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)  # before the window
    with pytest.raises(DATAFEED.DataFeedError, match="no session"):
        DATAFEED.resolve_as_of(df_clock_closed, df_calendar, now=now)


@requires_datafeed
def test_gb_d_15_now_must_be_timezone_aware(df_clock_closed, df_calendar):
    """GB-D-15: a naive `now` means something different on the other pod's box.

    Uses the closed clock deliberately: `now` is validated before the clock is
    ever inspected, so market state is irrelevant here and depending on it would
    be a dependency this criterion does not have.
    """
    with pytest.raises(ValueError, match="timezone-aware"):
        DATAFEED.resolve_as_of(df_clock_closed, df_calendar,
                               now=datetime(2026, 9, 2, 15, 30))


@requires_datafeed
def test_gb_d_16_half_days_and_holidays_come_from_the_calendar(df_clock_closed,
                                                               df_calendar_halfday):
    """GB-D-16: 6c's reason for existing, made executable.

    Thanksgiving week 2026: the calendar omits Nov 26 entirely and closes Nov 27
    at 13:00. A hand-rolled "16:00 every weekday" rule gets BOTH days wrong, and
    each wrong answer means screening against dead data on a live day.
    """
    now = datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)  # after the half-day close
    resolved = DATAFEED.resolve_as_of(df_clock_closed, df_calendar_halfday, now=now)

    assert resolved == datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc), (
        "13:00 America/New_York on the half day"
    )
    assert resolved != datetime(2026, 11, 27, 21, 0, tzinfo=timezone.utc), (
        "a hand-rolled 16:00 rule"
    )
    assert resolved.date() != datetime(2026, 11, 26).date(), (
        "Thanksgiving is not a session and the venue's calendar does not list it"
    )


# ---------------------------------------------------------------------------
# GB-D-17..22 — provenance, the paper guard, and failure
# ---------------------------------------------------------------------------

@requires_datafeed
def test_gb_d_17_every_observation_carries_the_as_of_it_is_true_at(
    df_contracts_pages, df_snapshots_body, df_account, df_positions, df_clock_closed
):
    """GB-D-17: a stale read is detectable rather than silently trusted."""
    as_of = LAST_CLOSE
    feed, _ = feed_with({
        CONTRACTS_PATH: paged_contracts(df_contracts_pages),
        SNAPSHOTS_PATH: df_snapshots_body,
        ACCOUNT_PATH: df_account,
        POSITIONS_PATH: df_positions,
        CLOCK_PATH: df_clock_closed,
    })
    observations = [
        feed.fetch_contracts(UNDERLYING, as_of=as_of, **WINDOW),
        feed.fetch_snapshots(["SPY260925C00500000"], as_of=as_of),
        feed.fetch_raw_account_state(as_of=as_of),
    ]
    for observation in observations:
        assert observation["as_of"] == "2026-09-01T20:00:00Z", (
            "ISO-8601 UTC, the same normalisation the ledger writes"
        )

    # The clock is the one read whose as_of is its own: it reports the venue's
    # time, so stamping our own on it would be inventing a second answer.
    assert "timestamp" in feed.fetch_clock()


@requires_datafeed
def test_gb_d_18_the_paper_guard_fires_before_any_request(df_clock_closed):
    """GB-D-18: paper-only (CLAUDE.md), enforced at the loader AND at the wire."""
    live = dict(FAKE_CONFIG, trading_base_url="https://api.alpaca.markets")

    with pytest.raises(DATAFEED.DataFeedError, match="paper"):
        DATAFEED.load_config(env={
            "ALPACA_API_KEY": "x" * 20, "ALPACA_SECRET_KEY": "y" * 20,
            "ALPACA_TRADING_BASE_URL": "https://api.alpaca.markets",
            "ALPACA_DATA_BASE_URL": "https://data.alpaca.markets",
        })

    # And again for a config built by hand, which is the path that would
    # otherwise walk around the loader.
    session = RecordedSession({CLOCK_PATH: df_clock_closed})
    feed = DATAFEED.DataFeed(live, session=session)
    with pytest.raises(DATAFEED.DataFeedError, match="paper"):
        feed.fetch_clock()
    assert session.requests == [], "not one request may leave for a live endpoint"


@requires_datafeed
def test_gb_d_19_auth_is_sent_and_the_suite_never_sees_a_secret(df_clock_closed):
    """GB-D-19: header NAMES are asserted; header values never enter the suite."""
    feed, session = feed_with({CLOCK_PATH: df_clock_closed})
    feed.fetch_clock()
    assert session.requests, "the fetch made no request"
    for request in session.requests:
        assert "APCA-API-KEY-ID" in request["header_names"]
        assert "APCA-API-SECRET-KEY" in request["header_names"]
        assert request["timeout"], "every request carries a timeout"


@requires_datafeed
def test_gb_d_20_a_bad_response_raises_rather_than_returning_something(df_clock_closed):
    """GB-D-20: a 500 and a non-JSON 200 are both errors, not empty data."""
    feed, _ = feed_with({CLOCK_PATH: RecordedResponse(500, {}, text="server error")})
    with pytest.raises(DATAFEED.DataFeedError, match="500"):
        feed.fetch_clock()

    feed, _ = feed_with({CLOCK_PATH: RecordedResponse(200, NOT_JSON, text="<html>")})
    with pytest.raises(DATAFEED.DataFeedError, match="not JSON"):
        feed.fetch_clock()


@requires_datafeed
def test_gb_d_21_the_clock_must_actually_say_whether_the_market_is_open():
    """GB-D-21: `market_open` (3a) is gated on this boolean; it is not optional."""
    feed, _ = feed_with({CLOCK_PATH: {"timestamp": "2026-09-02T11:39:16Z"}})
    with pytest.raises(DATAFEED.DataFeedError, match="is_open"):
        feed.fetch_clock()


@requires_datafeed
def test_gb_d_22_nanosecond_wire_timestamps_parse(df_clock_closed, df_snapshots_body):
    """GB-D-22: RFC3339 out of Alpaca carries nanoseconds; datetime carries micros."""
    stamp = DATAFEED.parse_wire_ts(df_clock_closed["timestamp"])
    assert stamp.tzinfo is not None
    for snapshot in df_snapshots_body["snapshots"].values():
        assert DATAFEED.parse_wire_ts(snapshot["latestQuote"]["t"]).tzinfo is not None
    with pytest.raises(ValueError, match="RFC3339"):
        DATAFEED.parse_wire_ts("the day before yesterday")


# ---------------------------------------------------------------------------
# The live band — off by default
# ---------------------------------------------------------------------------

@pytest.mark.live
@requires_datafeed
def test_gb_d_live_01_dev_account_smoke():
    """GB-D-live-01: one read-only round trip against the DEV paper account.

    SKIPPED unless `--live` is passed. It reads the clock and the account and
    nothing else: no orders endpoint is reachable from this module, and the
    paper guard has already refused any base URL that is not paper.

    It exists because a suite of recordings can go on passing forever after the
    venue changes a field. This is the one test that would notice.
    """
    DATAFEED.load_dotenv(".env")
    config = DATAFEED.load_config()
    feed = DATAFEED.DataFeed(config)

    clock = feed.fetch_clock()
    assert isinstance(clock["is_open"], bool)

    now = DATAFEED.parse_wire_ts(clock["timestamp"])
    state = feed.fetch_raw_account_state(as_of=now)
    assert set(state) == set(RAW_ACCOUNT_FIELDS)
    assert state["cash"] >= 0
