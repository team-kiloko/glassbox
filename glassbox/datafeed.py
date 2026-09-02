"""Data layer — GB_INTERFACES.md shapes 2b (RAW), 6, and 6c.

The dumb, honest reporter. Everything else in GlassBox is pure: the screener has
no clock, the governor has no I/O, the ledger has no wall clock. This module is
where the outside world is allowed in, and its whole job is to let it in *once*,
in one place, in a shape the pure modules can consume — and then to get out of
the way.

What that costs it, deliberately:

* **It holds no opinions.** It emits shape 2b **RAW** broker state and nothing
  else: `cash`, `buying_power`, `positions[].shares`, `as_of`. No `reserved_cash`,
  no `reserved_shares`. Reservations are derived from the ledger **by the
  governor** (A2 b), and a data layer that guessed at them would be a second
  source of truth for the one number coverage turns on.
* **It never reads a clock.** `as_of` is passed in, exactly as `ts` is passed to
  the ledger writer and `as_of` to the screener. :func:`resolve_as_of` implements
  the 6c policy, and even it takes `now` as an argument rather than reading it —
  a scheduling edge may read the wall clock; a library may not.
* **It hand-rolls no market calendar.** Holidays, half-days and early closes are
  exactly the cases a hand-rolled calendar gets wrong, and getting one wrong
  means screening against dead data or refusing to screen on a live day (6c).
  `/v2/clock` says whether the market is open; `/v2/calendar` says when the last
  session closed. Nothing here second-guesses either.

Three properties the contract suite holds it to:

1. **Every returned observation carries the `as_of` it is true at**, so a stale
   read is detectable rather than silently trusted. The clock's own `timestamp`
   is its `as_of`; the calendar is a published schedule, not an observation, and
   is passed through verbatim.
2. **Paginated fetches run to completion.** `/v2/options/contracts` paginates
   **nearest-expiry-first**, so a caller that stops at page one gets the front
   week no matter which expiry it asked for. Both fetchers follow
   `next_page_token` to exhaustion and return it explicitly as `null` — a
   positive statement that the fetch finished, the same discipline as shape 5's
   nullable `order`/`fill`.
3. **The paper guard fires before any request.** CLAUDE.md: the trading base URL
   must contain "paper". :func:`load_config` raises, and every request re-checks,
   so no code path can reach a live endpoint even with a hand-built config.

Transport is injectable: pass any object exposing
``get(url, headers=, params=, timeout=)`` returning a response with
``status_code``, ``json()`` and ``text``. The contract suite passes a session
backed by recorded bodies, and **no test in this repo touches the network**.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, time as _time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from glassbox.ledger import iso_utc  # one definition of an audit timestamp

__all__ = [
    "DataFeed", "DataFeedError", "load_config", "load_dotenv", "resolve_as_of",
    "parse_wire_ts", "build_raw_account_state", "MARKET_TZ",
]

#: The exchange calendar's own timezone. Not a tunable and not a hand-rolled
#: calendar: the session times in /v2/calendar are published in this zone, and
#: this is the conversion that reads them, nothing more.
MARKET_TZ = ZoneInfo("America/New_York")

#: How long we wait on a socket. An operational bound on this process, not a
#: trading threshold — nothing about a decision changes if it moves.
DEFAULT_TIMEOUT_SECONDS = 15

#: Symbols per snapshots request. A URL-length bound, same category as above.
_SYMBOLS_PER_REQUEST = 100

#: A paginated fetch that has not terminated by here is looping, not working.
_MAX_PAGES = 200

#: RFC3339 out of Alpaca carries nanoseconds; datetime resolves microseconds.
_SUBSECOND = re.compile(r"\.(\d{6})\d+")

_ENV_KEYS = (
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_TRADING_BASE_URL",
    "ALPACA_DATA_BASE_URL",
)


class DataFeedError(RuntimeError):
    """A request failed, or a response was not the shape the seam expects."""


# ---------------------------------------------------------------------------
# The one config loader
# ---------------------------------------------------------------------------

def load_dotenv(path=".env"):
    """Populate the environment from a `.env` file, without overriding it.

    Deliberately separate from :func:`load_config`: this is an edge convenience
    for scripts, and it is the only place in the package that reads a file.
    Real environment variables win, so a session that exports a key is never
    silently overridden by a stale file.
    """
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_config(env=None):
    """Read the data layer's whole configuration from the environment.

    One loader, at the edge, exactly once — the same rule the screener's
    thresholds follow (6a). No module below this reads an environment variable,
    so there is one place to look for what a run was pointed at.

    **The paper guard lives here** (CLAUDE.md): a trading base URL that does not
    contain "paper" raises immediately, before any object capable of making a
    request exists. Secrets are returned for use, never logged or echoed.
    """
    environment = os.environ if env is None else env
    missing = [key for key in _ENV_KEYS if not environment.get(key)]
    if missing:
        raise DataFeedError(
            "environment is missing " + ", ".join(missing)
            + " — fill .env from the team vault (see .env.example); this module "
            "has no defaults and will not guess an endpoint"
        )

    config = {
        "api_key": environment["ALPACA_API_KEY"],
        "secret_key": environment["ALPACA_SECRET_KEY"],
        "trading_base_url": environment["ALPACA_TRADING_BASE_URL"].rstrip("/"),
        "data_base_url": environment["ALPACA_DATA_BASE_URL"].rstrip("/"),
    }
    _assert_paper(config["trading_base_url"])
    return config


def _assert_paper(trading_base_url):
    """CLAUDE.md: paper trading only. Raise before a request, never after."""
    if "paper" not in (trading_base_url or ""):
        raise DataFeedError(
            f"refusing to run: the trading base URL is not a paper endpoint "
            f"({trading_base_url!r}). GlassBox is paper-only (CLAUDE.md); if this "
            f"is deliberate, stop and raise it with both humans rather than "
            f"editing this check"
        )


# ---------------------------------------------------------------------------
# Wire timestamps
# ---------------------------------------------------------------------------

def parse_wire_ts(value):
    """Parse an Alpaca RFC3339 timestamp into an aware datetime.

    The wire carries **nanoseconds** (`2026-09-02T07:39:16.780136595-04:00`) and
    `datetime` resolves microseconds, so the tail is truncated deliberately
    rather than left to blow up somewhere downstream. This lives here because
    the data layer is the module that meets the wire; nothing above it should be
    reimplementing RFC3339.
    """
    if not isinstance(value, str):
        raise ValueError(f"not a timestamp: {value!r}")
    text = _SUBSECOND.sub(r".\1", value.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"not an RFC3339 timestamp: {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 6c — the as_of policy
# ---------------------------------------------------------------------------

def resolve_as_of(clock, calendar, now):
    """The `as_of` a run screens and prices against (GB_INTERFACES.md 6c).

    Market **open** -> ``now``. Market **closed** -> the **last close**, read off
    ``/v2/calendar`` and bounded by ``now``.

    ``now`` is a required, timezone-aware argument. This function does not read
    the wall clock: a component that did could not be replayed, and `as_of` is
    the field the whole audit trail hangs off (shape 5).

    No calendar is hand-rolled here. The last close is the latest session in the
    supplied calendar whose close has already happened; if the window contains no
    such session the call **raises** rather than inventing one, because screening
    against a guessed timestamp is worse than not screening.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime, passed in by the caller")
    is_open = clock.get("is_open") if isinstance(clock, dict) else None
    if not isinstance(is_open, bool):
        raise DataFeedError("clock has no boolean 'is_open' (/v2/clock)")

    if is_open:
        return now.astimezone(timezone.utc)

    closes = [c for c in (_session_close(session) for session in calendar or [])
              if c is not None and c <= now]
    if not closes:
        raise DataFeedError(
            "the market is closed and the supplied /v2/calendar window contains no "
            "session that has already closed, so there is no last close to screen "
            "against. Widen the calendar window rather than defaulting a timestamp"
        )
    return max(closes).astimezone(timezone.utc)


def _session_close(session):
    """The UTC datetime a /v2/calendar session closed, or None if unreadable."""
    if not isinstance(session, dict):
        return None
    day, close = session.get("date"), session.get("close")
    if not isinstance(day, str) or not isinstance(close, str):
        return None
    try:
        parts = [int(p) for p in close.split(":")]
        local = datetime.combine(
            datetime.strptime(day, "%Y-%m-%d").date(),
            _time(parts[0], parts[1] if len(parts) > 1 else 0),
            tzinfo=MARKET_TZ,
        )
    except (ValueError, IndexError):
        return None
    return local.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# The feed
# ---------------------------------------------------------------------------

class DataFeed:
    """Alpaca reads, over an injectable transport.

    Args:
        config: the mapping :func:`load_config` returns.
        session: anything exposing ``get(url, headers=, params=, timeout=)``.
            Defaults to a ``requests.Session``, created lazily so that building
            a DataFeed never opens a socket — which is what lets the contract
            suite construct one with recorded bodies and never reach the network.
        timeout: seconds, operational.
    """

    def __init__(self, config, session=None, timeout=DEFAULT_TIMEOUT_SECONDS):
        for key in ("api_key", "secret_key", "trading_base_url", "data_base_url"):
            if not config.get(key):
                raise DataFeedError(f"config is missing {key} (see load_config)")
        self.config = config
        self.timeout = timeout
        self._session = session

    # -- transport ---------------------------------------------------------

    @property
    def session(self):
        if self._session is None:
            import requests  # imported here so the package never needs it to load

            self._session = requests.Session()
        return self._session

    def _base(self, host):
        if host == "trading":
            base = self.config["trading_base_url"]
            # Re-checked per request, not only at load: a hand-built config must
            # not be able to reach a live endpoint either.
            _assert_paper(base)
            return base
        if host == "data":
            return self.config["data_base_url"]
        raise ValueError(f"unknown host {host!r} (expected 'trading' or 'data')")

    def get_raw(self, host, path, params=None):
        """One GET, returning the parsed body verbatim. No shaping, no as_of."""
        url = self._base(host) + path
        headers = {
            "APCA-API-KEY-ID": self.config["api_key"],
            "APCA-API-SECRET-KEY": self.config["secret_key"],
            "accept": "application/json",
        }
        response = self.session.get(
            url, headers=headers, params=params or {}, timeout=self.timeout
        )
        status = getattr(response, "status_code", None)
        if status != 200:
            raise DataFeedError(
                f"GET {path} returned {status}: {str(getattr(response, 'text', ''))[:300]}"
            )
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise DataFeedError(f"GET {path} returned a body that is not JSON: {exc}") from None

    def _paginate(self, host, path, params, collect):
        """Follow next_page_token to exhaustion. Returns (payload, pages)."""
        page_params = dict(params)
        seen_tokens = set()
        pages = 0
        while True:
            body = self.get_raw(host, path, page_params)
            collect(body)
            pages += 1
            token = body.get("next_page_token")
            if not token:
                return pages
            if token in seen_tokens or pages >= _MAX_PAGES:
                raise DataFeedError(
                    f"GET {path} is not terminating: {pages} pages and the "
                    f"page token repeated. Refusing to loop"
                )
            seen_tokens.add(token)
            page_params["page_token"] = token

    # -- 6c pass-throughs --------------------------------------------------

    def fetch_clock(self):
        """`/v2/clock`, verbatim. Its own `timestamp` is the `as_of` it is true at."""
        clock = self.get_raw("trading", "/v2/clock")
        if not isinstance(clock, dict) or not isinstance(clock.get("is_open"), bool):
            raise DataFeedError("/v2/clock did not return a body with a boolean is_open")
        return clock

    def fetch_calendar(self, start, end):
        """`/v2/calendar`, verbatim. A published schedule, not an observation."""
        calendar = self.get_raw(
            "trading", "/v2/calendar", {"start": str(start), "end": str(end)}
        )
        if not isinstance(calendar, list):
            raise DataFeedError("/v2/calendar did not return a list of sessions")
        return calendar

    # -- the chain ---------------------------------------------------------

    def fetch_contracts(self, underlying, expiration_date_gte, expiration_date_lte,
                        as_of, limit=100, extra_params=None):
        """`/v2/options/contracts` for one underlying and one expiry window.

        **The expiry filter is not optional and the pagination is not optional.**
        This endpoint returns contracts **nearest-expiry-first**, so a caller that
        omits `expiration_date_gte`/`lte` and reads page one gets the front expiry
        whatever it wanted, and a caller that filters but stops early gets the
        near end of its own window. Both failures look like a thin chain rather
        than like a bug, which is why they are pinned by the contract suite.

        Returns the `/v2/options/contracts` body shape the screener consumes,
        with every page merged, plus the `as_of` it is true at and an explicit
        `next_page_token: null` saying the fetch ran out.
        """
        if not expiration_date_gte or not expiration_date_lte:
            raise ValueError(
                "expiration_date_gte and expiration_date_lte are required: this "
                "endpoint paginates nearest-expiry-first, so an unfiltered fetch "
                "silently returns the front expiry rather than the window asked for"
            )
        params = {
            "underlying_symbols": underlying,
            "expiration_date_gte": str(expiration_date_gte),
            "expiration_date_lte": str(expiration_date_lte),
            "limit": limit,
            **(extra_params or {}),
        }
        contracts = []

        def collect(body):
            page = body.get("option_contracts")
            if page is None:
                raise DataFeedError(
                    "/v2/options/contracts body has no 'option_contracts'"
                )
            contracts.extend(page)

        pages = self._paginate("trading", "/v2/options/contracts", params, collect)
        return {
            "option_contracts": contracts,
            "next_page_token": None,
            "pages": pages,
            "as_of": iso_utc(as_of),
        }

    def fetch_snapshots(self, symbols, as_of, feed="indicative", limit=100):
        """`/v1beta1/options/snapshots` for an explicit list of contract symbols.

        Returns exactly the shape-6 input the screener consumes — snapshots keyed
        by symbol under `snapshots` — with the `as_of` it is true at. Symbols are
        requested in chunks and every page of every chunk is followed; a symbol
        the venue has no snapshot for is simply absent, which the screener
        rejects as `no_snapshot` rather than skipping (shape 6).
        """
        symbols = list(symbols)
        if not symbols:
            raise ValueError("fetch_snapshots requires at least one symbol")
        merged = {}
        pages = 0

        def collect(body):
            page = body.get("snapshots")
            if page is None:
                raise DataFeedError(
                    "/v1beta1/options/snapshots body has no 'snapshots'"
                )
            merged.update(page)

        for start in range(0, len(symbols), _SYMBOLS_PER_REQUEST):
            chunk = symbols[start:start + _SYMBOLS_PER_REQUEST]
            pages += self._paginate(
                "data", "/v1beta1/options/snapshots",
                {"symbols": ",".join(chunk), "feed": feed, "limit": limit},
                collect,
            )
        return {
            "snapshots": merged,
            "next_page_token": None,
            "pages": pages,
            "as_of": iso_utc(as_of),
        }

    # -- 2b RAW ------------------------------------------------------------

    def fetch_raw_account_state(self, as_of):
        """Shape 2b **RAW** broker state. No reservations, ever (A2 b).

        `cash`, `buying_power` and `positions[].shares` exactly as the broker
        reports them, cast from the wire's strings, stamped with the `as_of` they
        are true at. The governor composes `reserved_cash` / `reserved_shares`
        onto this from the ledger; it raises if handed this raw state where its
        composed view belongs, so the two cannot be confused in either direction.

        **Only equity positions become `shares`.** An option position is a
        contract, not stock: counting a short call as -1 share would make a naked
        short look covered by arithmetic, which is the single worst mistake this
        function could make.
        """
        return build_raw_account_state(
            self.get_raw("trading", "/v2/account"),
            self.get_raw("trading", "/v2/positions"),
            as_of,
        )


def build_raw_account_state(account, positions, as_of):
    """The 2b RAW shape, out of `/v2/account` and `/v2/positions` bodies.

    Split out from the fetch so the contract suite can hold the mapping to
    recorded bodies without a transport in the way.
    """
    if not isinstance(account, dict):
        raise DataFeedError("/v2/account did not return a body")
    if not isinstance(positions, list):
        raise DataFeedError("/v2/positions did not return a list")

    shares = {}
    for position in positions:
        if position.get("asset_class") != "us_equity":
            continue  # an option position is contracts, not shares
        symbol = position.get("symbol")
        if not symbol:
            raise DataFeedError(f"position has no symbol: {position!r}")
        shares.setdefault(symbol, {"shares": 0})
        # FLOOR, not round: Alpaca reports fractional equity shares, and the
        # conservative direction differs by sign. Flooring under-counts a long
        # (99.7 -> 99) and over-counts a short (-0.5 -> -1), so a coverage check
        # reading this can only ever be too strict, never too generous.
        shares[symbol]["shares"] += math.floor(_number(position, "qty", symbol))

    return {
        "as_of": iso_utc(as_of),
        "cash": _number(account, "cash", "account"),
        "buying_power": _number(account, "buying_power", "account"),
        "positions": shares,
    }


def _number(body, field, context):
    """Cast a wire value to float. Alpaca returns numerics as strings."""
    value = body.get(field)
    if isinstance(value, bool) or value is None:
        raise DataFeedError(f"{context}.{field} is absent or not numeric: {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise DataFeedError(
            f"{context}.{field} is not numeric: {value!r} — failing closed rather "
            f"than defaulting a balance to zero"
        ) from None
