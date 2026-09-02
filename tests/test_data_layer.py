"""GB-D — data-layer contract suite (offline).

Mocks ``requests.Session.get`` at the session level; no network. The data
layer is a dumb reporter, so these tests assert that it passes broker shapes
through untouched, refuses non-paper endpoints, and applies exactly one policy
(``resolve_as_of``, A5 option a).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from glassbox import data_layer as dl
from glassbox.data_layer import AlpacaClient, ConfigError, DataLayerError

FIXTURES = Path(__file__).parent / "fixtures"

PAPER = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"


def _load(name):
    with (FIXTURES / name).open() as fh:
        return json.load(fh)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class Router:
    """Route mocked GETs by URL; record every call (url, params) for assertions."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, url, handler):
        self.routes[url] = handler

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {}), timeout))
        handler = self.routes.get(url)
        if handler is None:
            return FakeResponse(404, {"message": f"unrouted {url}"})
        result = handler(params or {})
        return result if isinstance(result, FakeResponse) else FakeResponse(200, result)


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: r(url, **kw))
    return r


@pytest.fixture
def client():
    return AlpacaClient("key-placeholder", "secret-placeholder", PAPER, DATA)


# ---------------------------------------------------------------------------
# 1–2. construction from env
# ---------------------------------------------------------------------------


def test_from_env_refuses_non_paper_trading_url():
    env = {
        "ALPACA_API_KEY": "k",
        "ALPACA_SECRET_KEY": "s",
        "ALPACA_TRADING_BASE_URL": "https://api.alpaca.markets",
        "ALPACA_DATA_BASE_URL": DATA,
    }
    with pytest.raises(ConfigError, match="paper"):
        AlpacaClient.from_env(env)


def test_constructor_refuses_non_paper_trading_url():
    with pytest.raises(ConfigError, match="paper"):
        AlpacaClient("k", "s", "https://api.alpaca.markets", DATA)


def test_from_env_missing_keys_names_the_variables():
    with pytest.raises(ConfigError) as info:
        AlpacaClient.from_env({"ALPACA_TRADING_BASE_URL": PAPER})
    message = str(info.value)
    assert "ALPACA_API_KEY" in message
    assert "ALPACA_SECRET_KEY" in message


def test_from_env_builds_client_and_sets_headers(router):
    env = {
        "ALPACA_API_KEY": "key-placeholder",
        "ALPACA_SECRET_KEY": "secret-placeholder",
        "ALPACA_TRADING_BASE_URL": PAPER,
        "ALPACA_DATA_BASE_URL": DATA,
    }
    c = AlpacaClient.from_env(env)
    router.add(f"{PAPER}/v2/clock", lambda p: {"is_open": True})
    dl.get_clock(c)
    _, _, headers, timeout = router.calls[0]
    assert headers["APCA-API-KEY-ID"] == "key-placeholder"
    assert headers["APCA-API-SECRET-KEY"] == "secret-placeholder"
    assert timeout == 15
    assert "key-placeholder" not in repr(c)


# ---------------------------------------------------------------------------
# 3. contracts pagination
# ---------------------------------------------------------------------------


def test_get_contracts_follows_next_page_token_and_keeps_string_numerics(router, client):
    fixture = _load("contracts_spy_2026-09-18.json")
    all_contracts = fixture["option_contracts"]
    page1, page2 = all_contracts[:4], all_contracts[4:]

    def handler(params):
        if params.get("page_token") == "tok-2":
            return {"option_contracts": page2, "next_page_token": None}
        assert "page_token" not in params
        return {"option_contracts": page1, "next_page_token": "tok-2"}

    router.add(f"{PAPER}/v2/options/contracts", handler)
    body = dl.get_contracts(client, "SPY", "2026-09-18", "2026-09-18", limit=4)

    assert set(body) == {"option_contracts", "next_page_token"}
    assert body["next_page_token"] is None
    assert [c["symbol"] for c in body["option_contracts"]] == [c["symbol"] for c in all_contracts]
    assert len(router.calls) == 2
    first_params = router.calls[0][1]
    assert first_params["underlying_symbols"] == "SPY"
    assert first_params["expiration_date_gte"] == "2026-09-18"
    assert first_params["expiration_date_lte"] == "2026-09-18"
    assert first_params["limit"] == 4
    assert router.calls[1][1]["page_token"] == "tok-2"
    for c in body["option_contracts"]:
        for field in ("strike_price", "open_interest", "multiplier", "close_price"):
            assert isinstance(c[field], str), f"{c['symbol']}.{field} must stay a string"


# ---------------------------------------------------------------------------
# 4. snapshots pass-through
# ---------------------------------------------------------------------------


def test_get_snapshots_passes_null_greeks_through_and_invents_nothing(router, client):
    fixture = _load("snapshots_spy_2026-09-18.json")
    contracts = _load("contracts_spy_2026-09-18.json")["option_contracts"]
    router.add(f"{DATA}/v1beta1/options/snapshots/SPY", lambda p: fixture)

    body = dl.get_snapshots(client, "SPY")

    assert set(body) == {"snapshots", "next_page_token"}
    assert body["snapshots"] == fixture["snapshots"]  # byte-for-byte equal payload
    assert body["snapshots"]["SPY260918C00500000"]["greeks"] is None
    assert body["snapshots"]["SPY260918C00500000"]["impliedVolatility"] is None
    assert "SPY260918C00700000" not in body["snapshots"]  # absent stays absent
    assert len(body["snapshots"]) == len(contracts) - 1
    params = router.calls[0][1]
    assert params["feed"] == "indicative"
    assert params["limit"] == 100


def test_get_snapshots_by_symbols_paginates_and_merges(router, client):
    fixture = _load("snapshots_spy_2026-09-18.json")
    items = list(fixture["snapshots"].items())
    page1, page2 = dict(items[:3]), dict(items[3:])

    def handler(params):
        assert params["symbols"] == "SPY260918C00640000,SPY260918C00500000"
        if params.get("page_token") == "next":
            return {"snapshots": page2, "next_page_token": None}
        return {"snapshots": page1, "next_page_token": "next"}

    router.add(f"{DATA}/v1beta1/options/snapshots", handler)
    body = dl.get_snapshots(client, "SPY", symbols=["SPY260918C00640000", "SPY260918C00500000"])
    assert body["snapshots"] == fixture["snapshots"]
    assert len(router.calls) == 2


# ---------------------------------------------------------------------------
# 5. account_state shape 2b
# ---------------------------------------------------------------------------


def test_account_state_matches_shape_2b(router, client):
    router.add(
        f"{PAPER}/v2/account",
        lambda p: {"account_number": "PA000000", "status": "ACTIVE",
                   "cash": "98765.43", "buying_power": "197530.86"},
    )
    router.add(
        f"{PAPER}/v2/positions",
        lambda p: [
            {"symbol": "SPY", "asset_class": "us_equity", "qty": "200"},
            {"symbol": "NVDA", "asset_class": "us_equity", "qty": "50"},
            {"symbol": "SPY260918C00640000", "asset_class": "us_option", "qty": "1"},
        ],
    )
    state = dl.account_state(client)

    assert set(state) == {"as_of", "cash", "buying_power", "reserved_cash", "positions"}
    assert isinstance(state["cash"], float) and state["cash"] == 98765.43
    assert isinstance(state["buying_power"], float) and state["buying_power"] == 197530.86
    assert state["reserved_cash"] == 0.0 and isinstance(state["reserved_cash"], float)
    assert set(state["positions"]) == {"SPY", "NVDA"}  # option position is not shares
    for entry in state["positions"].values():
        assert set(entry) == {"shares", "reserved_shares"}
        assert isinstance(entry["shares"], int) and not isinstance(entry["shares"], bool)
        assert entry["reserved_shares"] == 0
    assert state["positions"]["SPY"]["shares"] == 200
    parsed = dl.parse_rfc3339(state["as_of"])
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60


def test_get_account_adds_as_of_and_keeps_raw_fields(router, client):
    router.add(f"{PAPER}/v2/account", lambda p: {"account_number": "PA000000", "cash": "1"})
    body = dl.get_account(client)
    assert body["account_number"] == "PA000000"
    assert body["cash"] == "1"  # raw pass-through, still a string here
    assert dl.parse_rfc3339(body["as_of"]).tzinfo is not None


def test_get_open_orders_requests_open_and_nested(router, client):
    router.add(f"{PAPER}/v2/orders", lambda p: [{"id": "o1", "legs": [{"id": "l1"}]}])
    orders = dl.get_open_orders(client)
    assert orders[0]["legs"][0]["id"] == "l1"
    params = router.calls[0][1]
    assert params["status"] == "open"
    assert params["nested"] == "true"


# ---------------------------------------------------------------------------
# 6. resolve_as_of policy (A5 option a)
# ---------------------------------------------------------------------------


def test_resolve_as_of_returns_now_when_open(router, client):
    router.add(f"{PAPER}/v2/clock", lambda p: {"is_open": True})
    before = datetime.now(timezone.utc)
    result = dl.resolve_as_of(client)
    after = datetime.now(timezone.utc)
    assert result.tzinfo == timezone.utc
    assert before <= result <= after
    assert [u for u, *_ in router.calls] == [f"{PAPER}/v2/clock"]


def test_resolve_as_of_returns_last_close_when_closed(router, client):
    # Sunday 2026-08-30 12:00 UTC; the last session was Friday 2026-08-28,
    # closing 16:00 America/New_York = 20:00 UTC (EDT).
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    router.add(f"{PAPER}/v2/clock", lambda p: {"is_open": False})
    router.add(
        f"{PAPER}/v2/calendar",
        lambda p: [
            {"date": "2026-08-27", "open": "09:30", "close": "16:00"},
            {"date": "2026-08-28", "open": "09:30", "close": "16:00"},
        ],
    )
    result = dl.resolve_as_of(client, now=now)
    assert result == datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
    params = router.calls[1][1]
    assert params["start"] == "2026-08-23"
    assert params["end"] == "2026-08-30"


def test_resolve_as_of_closed_premarket_uses_previous_session(router, client):
    # Monday 2026-08-31 12:00 UTC (08:00 ET) — today's session is in the
    # calendar but has not closed yet, so Friday's close is the answer.
    now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    router.add(f"{PAPER}/v2/clock", lambda p: {"is_open": False})
    router.add(
        f"{PAPER}/v2/calendar",
        lambda p: [
            {"date": "2026-08-28", "open": "09:30", "close": "16:00"},
            {"date": "2026-08-31", "open": "09:30", "close": "16:00"},
        ],
    )
    assert dl.resolve_as_of(client, now=now) == datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)


def test_resolve_as_of_closed_with_empty_calendar_raises(router, client):
    router.add(f"{PAPER}/v2/clock", lambda p: {"is_open": False})
    router.add(f"{PAPER}/v2/calendar", lambda p: [])
    with pytest.raises(DataLayerError):
        dl.resolve_as_of(client)


# ---------------------------------------------------------------------------
# 7. timestamps
# ---------------------------------------------------------------------------


def test_parse_rfc3339_handles_fixture_nanosecond_timestamps():
    fixture = _load("snapshots_spy_2026-09-18.json")
    for symbol, snap in fixture["snapshots"].items():
        for key in ("latestQuote", "latestTrade"):
            if key not in snap:
                continue
            raw = snap[key]["t"]
            parsed = dl.parse_rfc3339(raw)
            assert parsed.tzinfo == timezone.utc, symbol
            assert parsed.year == 2026
    assert dl.parse_rfc3339("2026-08-28T19:54:58.812734191Z") == datetime(
        2026, 8, 28, 19, 54, 58, 812734, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-08-28T19:55:00Z", datetime(2026, 8, 28, 19, 55, tzinfo=timezone.utc)),
        ("2026-08-28T19:55:00.5Z", datetime(2026, 8, 28, 19, 55, 0, 500000, tzinfo=timezone.utc)),
        ("2026-08-28T15:55:00-04:00", datetime(2026, 8, 28, 19, 55, tzinfo=timezone.utc)),
        ("2026-08-28T19:55:00.123456789+00:00",
         datetime(2026, 8, 28, 19, 55, 0, 123456, tzinfo=timezone.utc)),
    ],
)
def test_parse_rfc3339_variants(raw, expected):
    assert dl.parse_rfc3339(raw) == expected


def test_parse_rfc3339_rejects_garbage():
    with pytest.raises(ValueError):
        dl.parse_rfc3339("")
    with pytest.raises(ValueError):
        dl.parse_rfc3339("not a timestamp")


# ---------------------------------------------------------------------------
# 8. errors
# ---------------------------------------------------------------------------


def test_non_200_raises_data_layer_error_with_status(router, client):
    router.add(
        f"{PAPER}/v2/account",
        lambda p: FakeResponse(403, {"message": "forbidden."}, text='{"message": "forbidden."}'),
    )
    with pytest.raises(DataLayerError) as info:
        dl.get_account(client)
    assert info.value.status == 403
    assert "forbidden" in info.value.body
    assert "403" in str(info.value)


def test_transport_failure_raises_data_layer_error(monkeypatch, client):
    def boom(session, url, **kwargs):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests.Session, "get", boom)
    with pytest.raises(DataLayerError) as info:
        dl.get_clock(client)
    assert info.value.status is None


def test_pagination_loop_is_refused(router, client):
    router.add(f"{PAPER}/v2/options/contracts",
               lambda p: {"option_contracts": [], "next_page_token": "same"})
    with pytest.raises(DataLayerError, match="pagination loop"):
        dl.get_contracts(client, "SPY", "2026-09-18", "2026-09-18")
