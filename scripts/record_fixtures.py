#!/usr/bin/env python3
"""Record the GB-D data-layer fixtures ONCE from the DEV paper account.

The data layer is I/O by nature, so its contract suite must never touch the
network: GB-D runs against the bodies this script records. Recording is a
deliberate, human-run act — not something a test does — which is why it lives in
`scripts/` and writes files a human then reads and commits.

What it records, into `tests/fixtures/datafeed/`:

    contracts_page1.json      /v2/options/contracts, page 1 (carries a
    contracts_page2.json      next_page_token) and the page it points at
    snapshots_indicative.json /v1beta1/options/snapshots, feed=indicative
    account.json              /v2/account
    positions.json            /v2/positions
    clock_open.json           /v2/clock  — whichever state is live when you run
    clock_closed.json         /v2/clock  — the other one; re-run at the open
    calendar.json             /v2/calendar
    recording.json            what was asked for, and when. No credentials.

Two safety properties, both enforced rather than asserted:

* **Nothing is written that contains a credential.** Every file is serialized
  first and scanned for the live key and secret before it reaches disk; a hit
  aborts the whole run. Headers are never recorded at all.
* **Account identity is scrubbed down to the account id.** The id is kept
  deliberately — the submission needs an account id and a fixture that cannot
  name its account is not a recording of anything. `account_number` and any
  contact-shaped field go.

The paper guard from CLAUDE.md is inherited from `glassbox.datafeed`: the trading
base URL must contain "paper" or the config loader raises before a request is
made.

Usage:
    python scripts/record_fixtures.py            # everything
    python scripts/record_fixtures.py --only clock   # just re-record the clock

Re-running never overwrites the OTHER clock state: /v2/clock reports one state at
a time, so the pair is built by running this once while the market is closed and
once while it is open. Nothing is derived, hand-edited, or invented.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from glassbox.datafeed import (  # noqa: E402
    DataFeed,
    load_config,
    load_dotenv,
)

FIXTURES = REPO / "tests" / "fixtures" / "datafeed"
CONFIG = REPO / "config" / "datafeed.PROPOSED.json"

#: Dropped from /v2/account. `id` is deliberately NOT here.
_ACCOUNT_SCRUB = ("account_number",)

#: Dropped from any recorded body, wherever they appear. None of these is
#: returned by the endpoints we record today; they are here so that a future
#: endpoint cannot quietly introduce one.
_IDENTITY_SCRUB = ("email", "email_address", "phone", "phone_number",
                   "given_name", "family_name", "owner", "ssn", "tax_id")


def _scrub(value, drop):
    if isinstance(value, dict):
        return {k: _scrub(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [_scrub(item, drop) for item in value]
    return value


def _write(name, body, secrets, note=None):
    """Serialize, refuse if a credential is anywhere in the bytes, then write."""
    text = json.dumps(body, indent=2, sort_keys=False) + "\n"
    for secret in secrets:
        if secret and secret in text:
            raise SystemExit(
                f"ABORT: a credential appeared in the body for {name}. Nothing "
                f"was written. This is a bug in the recorder or a very unusual "
                f"response; do not work around it."
            )
    path = FIXTURES / name
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.relative_to(REPO)}  ({len(text):,} bytes)"
          + (f"  — {note}" if note else ""))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("all", "clock"), default="all")
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    config = load_config()           # raises unless the trading URL is paper
    tunables = json.loads(CONFIG.read_text(encoding="utf-8"))
    secrets = (config["api_key"], config["secret_key"])

    FIXTURES.mkdir(parents=True, exist_ok=True)
    feed = DataFeed(config)
    recorded_at = datetime.now(timezone.utc)
    manifest = {
        "_note": (
            "Recorded from the DEV paper account by scripts/record_fixtures.py. "
            "Account identity is scrubbed to the account id; no credential is "
            "written anywhere in this directory. Bodies are verbatim otherwise."
        ),
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "requests": [],
    }
    manifest_path = FIXTURES / "recording.json"
    if manifest_path.exists():
        manifest["requests"] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        ).get("requests", [])

    def remember(name, endpoint, params):
        manifest["requests"] = [
            r for r in manifest["requests"] if r["file"] != name
        ] + [{
            "file": name, "endpoint": endpoint, "params": params,
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        }]

    # -- the clock, always -------------------------------------------------
    print("recording /v2/clock ...")
    clock = feed.fetch_clock()
    state = "open" if clock["is_open"] else "closed"
    name = f"clock_{state}.json"
    _write(name, clock, secrets, note=f"market is {state} right now")
    remember(name, "/v2/clock", {})
    other = FIXTURES / f"clock_{'closed' if clock['is_open'] else 'open'}.json"
    if not other.exists():
        print(f"  NOTE: {other.name} does not exist yet. /v2/clock reports one "
              f"state at a time — re-run `--only clock` while the market is "
              f"{'closed' if clock['is_open'] else 'open'}. Nothing is derived.")

    if args.only == "all":
        underlying = tunables["underlying"]
        today = date.today()
        # The recorder keeps its OWN band so re-recording reproduces the
        # committed fixtures rather than following the live band around.
        gte = (today + timedelta(days=tunables["fixture_dte_min_days"])).isoformat()
        lte = (today + timedelta(days=tunables["fixture_dte_max_days"])).isoformat()
        page_limit = tunables["fixture_page_limit"]

        # -- contracts, two pages, verbatim -------------------------------
        print(f"recording /v2/options/contracts ({underlying} {gte}..{lte}) ...")
        params = {
            "underlying_symbols": underlying,
            "expiration_date_gte": gte,
            "expiration_date_lte": lte,
            "type": tunables["fixture_type"],
            "strike_price_gte": tunables["fixture_strike_gte"],
            "strike_price_lte": tunables["fixture_strike_lte"],
            "limit": page_limit,
        }
        page1 = feed.get_raw("trading", "/v2/options/contracts", params)
        token = page1.get("next_page_token")
        if not token:
            raise SystemExit(
                "ABORT: page 1 carried no next_page_token, so there is no "
                "two-page sample to record. Lower fixture_page_limit or widen "
                "the DTE band in config/datafeed.PROPOSED.json and re-run."
            )
        page2 = feed.get_raw(
            "trading", "/v2/options/contracts", {**params, "page_token": token}
        )
        if page2.get("next_page_token"):
            raise SystemExit(
                "ABORT: page 2 still carries a next_page_token, so this is two "
                "pages of a longer run and not a complete fetch. A fixture that "
                "cannot terminate cannot prove a fetcher terminates — narrow "
                "fixture_strike_gte/lte in config/datafeed.PROPOSED.json and re-run."
            )
        _write("contracts_page1.json", page1, secrets,
               note=f"{len(page1['option_contracts'])} contracts, token present")
        _write("contracts_page2.json", page2, secrets,
               note=f"{len(page2['option_contracts'])} contracts")
        remember("contracts_page1.json", "/v2/options/contracts", params)
        remember("contracts_page2.json", "/v2/options/contracts",
                 {**params, "page_token": "<token from page 1>"})

        # -- snapshots for exactly those symbols --------------------------
        symbols = [c["symbol"] for c in
                   page1["option_contracts"] + page2["option_contracts"]]
        print(f"recording /v1beta1/options/snapshots ({len(symbols)} symbols) ...")
        snap_params = {
            "symbols": ",".join(symbols),
            "feed": tunables["snapshot_feed"],
            "limit": tunables["page_limit"],
        }
        snapshots = feed.get_raw("data", "/v1beta1/options/snapshots", snap_params)
        _write("snapshots_indicative.json", snapshots, secrets,
               note=f"{len(snapshots.get('snapshots') or {})} snapshots")
        remember("snapshots_indicative.json", "/v1beta1/options/snapshots",
                 {**snap_params, "symbols": f"<{len(symbols)} symbols from the "
                                            f"contracts pages>"})

        # -- account, scrubbed --------------------------------------------
        print("recording /v2/account ...")
        account = _scrub(
            feed.get_raw("trading", "/v2/account", {}),
            drop=set(_ACCOUNT_SCRUB) | set(_IDENTITY_SCRUB),
        )
        _write("account.json", account, secrets,
               note="account_number scrubbed; id kept")
        remember("account.json", "/v2/account", {})

        # -- positions ------------------------------------------------------
        print("recording /v2/positions ...")
        positions = _scrub(
            feed.get_raw("trading", "/v2/positions", {}), drop=set(_IDENTITY_SCRUB)
        )
        _write("positions.json", positions, secrets,
               note=f"{len(positions)} open position(s)")
        remember("positions.json", "/v2/positions", {})

        # -- calendar -------------------------------------------------------
        start = (today - timedelta(days=tunables["calendar_lookback_days"])).isoformat()
        end = (today + timedelta(days=1)).isoformat()
        print(f"recording /v2/calendar ({start}..{end}) ...")
        cal_params = {"start": start, "end": end}
        calendar = feed.get_raw("trading", "/v2/calendar", cal_params)
        _write("calendar.json", calendar, secrets,
               note=f"{len(calendar)} session(s)")
        remember("calendar.json", "/v2/calendar", cal_params)

    manifest["requests"].sort(key=lambda r: r["file"])
    _write("recording.json", manifest, secrets)
    print("\nDone. Read what was written before committing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
