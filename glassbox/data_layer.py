"""GlassBox data layer — a dumb, honest reporter of Alpaca broker state.

Scope (GB_INTERFACES.SIGNOFF-DRAFT.md shape 2b, HANDOFF 2026-09-02 B1, Jhoosier lead):

* Every function takes an explicit ``AlpacaClient`` and returns plain dicts and
  lists in the raw REST shape. No judgment, no thresholds, no config file I/O,
  no caching across calls. The only function that decides anything is
  ``resolve_as_of``, and its decision is the signed A5 option (a) policy, not a
  threshold.
* ``requests`` against the REST endpoints directly (as scripts/verify_gate.py
  does). alpaca-py is deliberately not used here: the screener consumes the raw
  wire shapes recorded in tests/fixtures, and the SDK reshapes them.
* Paper trading only. The client constructor refuses any trading base URL that
  does not contain "paper" (CLAUDE.md).

Reservations — why ``reserved_cash`` and ``reserved_shares`` are always zero here
-------------------------------------------------------------------------------
Sign-off agenda item A2 was settled as option (b): the GOVERNOR owns
reservations, maintaining them from the provenance ledger. The data layer is a
reporter of what the broker says, and the broker has no notion of "shares
already committed to another covered call in this system". So ``account_state``
emits the shape-2b field names exactly as drafted, with ``reserved_cash: 0.0``
and ``reserved_shares: 0``. Those zeros are a positive statement: "the data
layer claims no reservations". The governor overlays its own ledger-derived
reservations before running the coverage / cash_floor checks. Do not "fix" this
by computing reservations from open orders here; that would create a second,
silently diverging source of truth for risk.

Timestamps
----------
Alpaca returns RFC3339 with nanosecond precision (fixtures README trap 6).
Python ``datetime`` carries microseconds. ``parse_rfc3339`` truncates to
microseconds deliberately, and everything in this module uses it.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

import requests

__all__ = [
    "DataLayerError",
    "ConfigError",
    "AlpacaClient",
    "parse_rfc3339",
    "get_account",
    "get_positions",
    "get_open_orders",
    "get_clock",
    "get_calendar",
    "get_contracts",
    "get_snapshots",
    "account_state",
    "resolve_as_of",
]

TIMEOUT_SECONDS = 15
BODY_EXCERPT_CHARS = 300

ENV_API_KEY = "ALPACA_API_KEY"
ENV_SECRET_KEY = "ALPACA_SECRET_KEY"
ENV_TRADING_BASE_URL = "ALPACA_TRADING_BASE_URL"
ENV_DATA_BASE_URL = "ALPACA_DATA_BASE_URL"

DEFAULT_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_DATA_BASE_URL = "https://data.alpaca.markets"

# Alpaca's calendar endpoint reports session times in exchange local time.
EXCHANGE_TZ = ZoneInfo("America/New_York")

# resolve_as_of looks back this many days for the most recent session close
# (covers a long weekend plus a holiday). Not a tunable: it is a search bound,
# not a judgment, and any real gap this wide is an error worth raising.
CALENDAR_LOOKBACK_DAYS = 7


class DataLayerError(Exception):
    """Broker returned a non-200, or the data layer could not do its job.

    ``status`` is the HTTP status (None when the failure was not an HTTP
    response); ``body`` is an excerpt of the response text, never the whole
    thing, so a log line stays a log line.
    """

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - formatting only
        base = super().__str__()
        if self.status is not None:
            return f"{base} [status={self.status}] {self.body}".rstrip()
        return base


class ConfigError(DataLayerError):
    """Client could not be built: missing env vars or a non-paper trading URL."""


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_FRACTION = re.compile(r"\.(\d{1,6})(\d*)")


def parse_rfc3339(value: str) -> datetime:
    """Parse an Alpaca RFC3339 timestamp into a timezone-aware UTC datetime.

    Nanosecond fractions are truncated (not rounded) to microseconds, which is
    the finest resolution ``datetime`` carries. A trailing ``Z`` and explicit
    offsets are both accepted; a naive string is taken as UTC.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"not an RFC3339 timestamp: {value!r}")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + m.group(1), text, count=1)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AlpacaClient:
    """Thin authenticated GET client for the Alpaca trading and data REST hosts."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        trading_base_url: str = DEFAULT_TRADING_BASE_URL,
        data_base_url: str = DEFAULT_DATA_BASE_URL,
        timeout: float = TIMEOUT_SECONDS,
    ):
        if "paper" not in (trading_base_url or ""):
            raise ConfigError(
                "trading base URL must be the paper endpoint (must contain 'paper'); "
                f"refusing {trading_base_url!r}"
            )
        if not api_key or not secret_key:
            raise ConfigError("api_key and secret_key are both required")
        self.trading_base_url = trading_base_url.rstrip("/")
        self.data_base_url = (data_base_url or DEFAULT_DATA_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        }
        self.session = requests.Session()

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AlpacaClient":
        """Build a client from ALPACA_* environment variables.

        Reads the process environment (or ``env`` if given). Does not read
        ``.env`` files: loading those is the caller's job, and secrets never
        pass through this module's output.
        """
        source = os.environ if env is None else env
        missing = [name for name in (ENV_API_KEY, ENV_SECRET_KEY) if not source.get(name)]
        if missing:
            raise ConfigError(
                "missing required environment variable(s): " + ", ".join(missing)
            )
        return cls(
            api_key=source[ENV_API_KEY],
            secret_key=source[ENV_SECRET_KEY],
            trading_base_url=source.get(ENV_TRADING_BASE_URL) or DEFAULT_TRADING_BASE_URL,
            data_base_url=source.get(ENV_DATA_BASE_URL) or DEFAULT_DATA_BASE_URL,
        )

    def __repr__(self) -> str:  # never echo keys
        return (
            f"AlpacaClient(trading_base_url={self.trading_base_url!r}, "
            f"data_base_url={self.data_base_url!r})"
        )

    # -- transport ----------------------------------------------------------

    def _get(self, url: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        try:
            response = self.session.get(
                url, headers=self._headers, params=dict(params or {}), timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise DataLayerError(f"request failed: GET {url}: {exc}") from exc
        if response.status_code != 200:
            excerpt = (response.text or "")[:BODY_EXCERPT_CHARS]
            raise DataLayerError(
                f"GET {url} returned {response.status_code}",
                status=response.status_code,
                body=excerpt,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DataLayerError(
                f"GET {url} returned non-JSON body",
                status=response.status_code,
                body=(response.text or "")[:BODY_EXCERPT_CHARS],
            ) from exc

    def trading_get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._get(self.trading_base_url + path, params)

    def data_get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._get(self.data_base_url + path, params)


# ---------------------------------------------------------------------------
# Raw pass-throughs (trading host)
# ---------------------------------------------------------------------------


def get_account(client: AlpacaClient) -> dict:
    """Raw ``GET /v2/account`` body plus ``as_of`` (UTC ISO, taken on arrival)."""
    body = client.trading_get("/v2/account")
    body = dict(body)
    body["as_of"] = _now_utc().isoformat()
    return body


def get_positions(client: AlpacaClient) -> list:
    """Raw ``GET /v2/positions`` body."""
    return list(client.trading_get("/v2/positions"))


def get_open_orders(client: AlpacaClient) -> list:
    """Raw ``GET /v2/orders?status=open``, nested ``legs`` included."""
    return list(client.trading_get("/v2/orders", {"status": "open", "nested": "true"}))


def get_clock(client: AlpacaClient) -> dict:
    """Raw ``GET /v2/clock``."""
    return dict(client.trading_get("/v2/clock"))


def get_calendar(client: AlpacaClient, start: str, end: str) -> list:
    """Raw ``GET /v2/calendar?start=..&end=..`` (YYYY-MM-DD). Nobody hand-rolls one."""
    return list(client.trading_get("/v2/calendar", {"start": start, "end": end}))


# ---------------------------------------------------------------------------
# Options chain (paginated)
# ---------------------------------------------------------------------------


def get_contracts(
    client: AlpacaClient,
    underlying: str,
    expiration_gte: str,
    expiration_lte: str,
    limit: int = 100,
) -> dict:
    """``GET /v2/options/contracts`` for one underlying and expiry window.

    Follows ``next_page_token`` until exhausted and concatenates
    ``option_contracts``. Returns the body in the exact shape of
    tests/fixtures/contracts_spy_2026-09-18.json. Numeric fields stay strings,
    as the endpoint returns them (fixtures README trap 5).
    """
    params: dict = {
        "underlying_symbols": underlying,
        "expiration_date_gte": expiration_gte,
        "expiration_date_lte": expiration_lte,
        "limit": limit,
    }
    contracts: list = []
    for page in _paginate(client.trading_get, "/v2/options/contracts", params):
        contracts.extend(page.get("option_contracts") or [])
    return {"option_contracts": contracts, "next_page_token": None}


def get_snapshots(
    client: AlpacaClient,
    underlying: str,
    symbols: Optional[Iterable[str]] = None,
    feed: str = "indicative",
    limit: int = 100,
) -> dict:
    """Option snapshots, in the exact shape of tests/fixtures/snapshots_spy_2026-09-18.json.

    With ``symbols=None`` this is ``GET /v1beta1/options/snapshots/{underlying}``
    (the whole chain). With ``symbols`` it is ``GET /v1beta1/options/snapshots``
    with the ``symbols`` query, which is Alpaca's by-contract variant and
    returns the same body shape. Either way ``next_page_token`` is followed
    and ``snapshots`` merged.

    Null greeks pass through as ``null``: never filled, zeroed, or dropped.
    Contracts missing from the response stay missing: absence is the
    screener's ``no_snapshot`` signal, not ours to paper over.
    """
    params: dict = {"feed": feed, "limit": limit}
    if symbols is None:
        path = f"/v1beta1/options/snapshots/{underlying}"
    else:
        symbol_list = [s for s in symbols]
        if not symbol_list:
            return {"snapshots": {}, "next_page_token": None}
        path = "/v1beta1/options/snapshots"
        params["symbols"] = ",".join(symbol_list)
    merged: dict = {}
    for page in _paginate(client.data_get, path, params):
        merged.update(page.get("snapshots") or {})
    return {"snapshots": merged, "next_page_token": None}


def _paginate(getter, path: str, params: Mapping[str, Any]):
    """Yield successive page bodies, following ``next_page_token`` to exhaustion."""
    page_params = dict(params)
    seen_tokens: set = set()
    while True:
        body = getter(path, page_params)
        yield body
        token = body.get("next_page_token") if isinstance(body, dict) else None
        if not token:
            return
        if token in seen_tokens:
            raise DataLayerError(f"pagination loop: token {token!r} repeated on {path}")
        seen_tokens.add(token)
        page_params = dict(params, page_token=token)


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------


def _money(value: Any) -> float:
    if value is None:
        raise DataLayerError("account field missing or null; refusing to guess a money value")
    return float(value)


def account_state(client: AlpacaClient) -> dict:
    """Shape 2b account state for the governor.

    ``{as_of, cash, buying_power, reserved_cash, positions: {UNDERLYING:
    {shares, reserved_shares}}}``. Money is float, shares is int. Only equity
    positions (``asset_class == "us_equity"``) count as shares; option
    positions are not shares and never cover anything. Reservations are zero
    by policy (A2 option b) — see the module docstring.
    """
    account = get_account(client)
    positions = get_positions(client)
    by_underlying: dict = {}
    for pos in positions:
        if pos.get("asset_class") != "us_equity":
            continue
        symbol = pos.get("symbol")
        if not symbol:
            continue
        shares = int(float(pos.get("qty", 0) or 0))
        by_underlying[symbol] = {"shares": shares, "reserved_shares": 0}
    return {
        "as_of": account["as_of"],
        "cash": _money(account.get("cash")),
        "buying_power": _money(account.get("buying_power")),
        "reserved_cash": 0.0,
        "positions": by_underlying,
    }


def resolve_as_of(client: AlpacaClient, now: Optional[datetime] = None) -> datetime:
    """The signed A5 option (a) ``as_of`` policy, timezone-aware UTC.

    Market open (per ``/v2/clock``) → now. Market closed → the most recent
    session close per ``/v2/calendar``, looking back up to
    ``CALENDAR_LOOKBACK_DAYS``. ``now`` is injectable for tests only; callers
    in the pipeline leave it unset.
    """
    now = (now or _now_utc()).astimezone(timezone.utc)
    clock = get_clock(client)
    if clock.get("is_open") is True:
        return now
    start = (now - timedelta(days=CALENDAR_LOOKBACK_DAYS)).date().isoformat()
    end = now.date().isoformat()
    closes = []
    for session in get_calendar(client, start, end):
        try:
            local_close = datetime.fromisoformat(f"{session['date']}T{session['close']}")
        except (KeyError, ValueError) as exc:
            raise DataLayerError(f"malformed calendar entry: {session!r}") from exc
        close_utc = local_close.replace(tzinfo=EXCHANGE_TZ).astimezone(timezone.utc)
        if close_utc <= now:
            closes.append(close_utc)
    if not closes:
        raise DataLayerError(
            f"no session close found between {start} and {end}; refusing to guess as_of"
        )
    return max(closes)
