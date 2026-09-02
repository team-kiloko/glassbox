"""GB-D-LIVE — opt-in read-only smoke test against the dev PAPER account.

Skipped unless ``GLASSBOX_LIVE=1``. Reads .env from the repo root (setdefault,
never printed) so the test can run the way scripts/verify_gate.py does. Every
call here is a GET; this module never builds, submits, or cancels an order.
"""

from __future__ import annotations

import calendar as _calendar
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("GLASSBOX_LIVE") != "1",
    reason="live paper-account smoke test; set GLASSBOX_LIVE=1 to run",
)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _third_friday(year: int, month: int) -> date:
    first_weekday = _calendar.monthrange(year, month)[0]  # Monday == 0
    first_friday = 1 + (_calendar.FRIDAY - first_weekday) % 7
    return date(year, month, first_friday + 14)


def _nearest_monthly(today: date) -> date:
    candidate = _third_friday(today.year, today.month)
    if candidate <= today:
        nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        candidate = _third_friday(nxt.year, nxt.month)
    return candidate


@pytest.fixture(scope="module")
def client():
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from glassbox.data_layer import AlpacaClient

    c = AlpacaClient.from_env()
    assert "paper" in c.trading_base_url
    return c


def test_live_account(client):
    from glassbox import data_layer as dl

    body = dl.get_account(client)
    assert body["status"] == "ACTIVE"
    assert "as_of" in body
    state = dl.account_state(client)
    assert set(state) == {"as_of", "cash", "buying_power", "reserved_cash", "positions"}


def test_live_clock_and_as_of(client):
    from glassbox import data_layer as dl

    clock = dl.get_clock(client)
    assert "is_open" in clock
    as_of = dl.resolve_as_of(client)
    assert as_of.tzinfo is not None


def test_live_contracts_and_snapshots(client):
    from glassbox import data_layer as dl

    expiry = _nearest_monthly(date.today()).isoformat()
    contracts = dl.get_contracts(client, "SPY", expiry, expiry, limit=100)
    assert set(contracts) == {"option_contracts", "next_page_token"}
    assert contracts["option_contracts"], f"no SPY contracts for {expiry}"
    assert isinstance(contracts["option_contracts"][0]["strike_price"], str)

    symbols = [c["symbol"] for c in contracts["option_contracts"][:20]]
    snaps = dl.get_snapshots(client, "SPY", symbols=symbols)
    assert set(snaps) == {"snapshots", "next_page_token"}
    # Absence is allowed (screener's no_snapshot); presence must be untouched raw.
    for symbol, snap in snaps["snapshots"].items():
        assert symbol in symbols
        assert "greeks" in snap
