#!/usr/bin/env python3
"""GlassBox phase-3 verification gate (SETUP.md step 5).

Runs the a/b/c checks against the paper environment using only stdlib +
requests (pinned in requirements.txt). Reads .env in the current directory
or real environment variables. Exits 0 only if ALL checks pass.

  a. Account read           GET {trading}/v2/account
  b. Equity bars (free iex) GET {data}/v2/stocks/SPY/bars
  c. Options chain          GET {trading}/v2/options/contracts (SPY)
                            GET {data}/v1beta1/options/snapshots/SPY (indicative)

Usage: python scripts/verify_gate.py
"""
import os
import sys

import requests

def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

def main():
    load_dotenv()
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    trading = os.environ.get("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets")
    data = os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
    if not key or not secret:
        print("FAIL  missing ALPACA_API_KEY / ALPACA_SECRET_KEY (fill .env from the vault)")
        return 1
    if "paper" not in trading:
        print(f"FAIL  trading base URL is not the paper endpoint: {trading}")
        return 1
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    failures = 0

    def check(label, url, params=None, expect_keys=()):
        nonlocal failures
        try:
            r = requests.get(url, headers=h, params=params or {}, timeout=15)
            body = r.json() if r.content else {}
            ok = r.status_code == 200 and all(k in body for k in expect_keys)
            print(f"{'PASS' if ok else 'FAIL'}  {label}  [{r.status_code}]")
            if not ok:
                failures += 1
                print(f"      {str(body)[:200]}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {label}  ({type(e).__name__}: {e})")

    check("a. account read", f"{trading}/v2/account", expect_keys=("account_number", "status"))
    check("b. SPY daily bars (iex)", f"{data}/v2/stocks/SPY/bars",
          params={"timeframe": "1Day", "limit": 5, "feed": "iex"}, expect_keys=("bars",))
    check("c1. SPY option contracts", f"{trading}/v2/options/contracts",
          params={"underlying_symbols": "SPY", "limit": 5}, expect_keys=("option_contracts",))
    check("c2. SPY option snapshots (indicative)", f"{data}/v1beta1/options/snapshots/SPY",
          params={"feed": "indicative", "limit": 5}, expect_keys=("snapshots",))

    print("\nGATE " + ("GREEN: post it in your HANDOFF block." if failures == 0
                       else f"RED: {failures} check(s) failed. Fix before building."))
    return 0 if failures == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
