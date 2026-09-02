# GB-D fixtures — recorded, not written

The data layer is I/O by nature, and a contract suite that reaches the network is
not a contract suite: it is green when the venue is up and red when it is not,
and it says nothing about our code either way. So **GB-D runs entirely against
the bodies in this directory**, served through an injectable transport. No test
in this repo touches the network.

Everything here except the two files marked `.HAND.json` was **recorded verbatim
from the DEV paper account** by `scripts/record_fixtures.py`. Re-record with:

    python scripts/record_fixtures.py            # everything
    python scripts/record_fixtures.py --only clock   # just the clock

`recording.json` says what was asked for and when.

## What is recorded

| File | Endpoint | Why it is here |
|---|---|---|
| `contracts_page1.json` | `/v2/options/contracts` | Page 1 of a COMPLETE run: 6 contracts, carrying a `next_page_token` |
| `contracts_page2.json` | `/v2/options/contracts` | The page it points at: 4 contracts, `next_page_token: null` |
| `snapshots_indicative.json` | `/v1beta1/options/snapshots` | `feed=indicative`, the ten symbols on those two pages |
| `account.json` | `/v2/account` | Balances, scrubbed |
| `positions.json` | `/v2/positions` | The dev account is flat, so this is `[]` — a real and load-bearing case |
| `clock_open.json` | `/v2/clock` | Market open |
| `clock_closed.json` | `/v2/clock` | Market closed |
| `calendar.json` | `/v2/calendar` | The sessions `resolve_as_of` reads the last close off |

**The clock pair takes two recordings.** `/v2/clock` reports one state at a
moment, so the pair is built by running the recorder once while the market is
closed and once while it is open. Neither file is derived from the other, and the
recorder refuses to invent the one it cannot see.

Until `clock_open.json` exists, **GB-D-F04 and GB-D-11 are strict-xfail on its
absence** (`conftest.requires_clock_open`) and **arm themselves the instant the
recorded file appears** — the same pattern the module probes use, and for the
same reason. This is a condition on a file's presence, not a stand-in for it: no
assertion is relaxed, and a fabricated open clock would make the suite pass
against data no venue ever sent.

## What is hand-authored, and why

Two cases the dev account cannot currently produce. Both are named `.HAND.json`
so no reader mistakes them for a recording, and both are built to the recorded
wire shape rather than to what the code happens to accept.

* **`positions_mixed.HAND.json`** — an equity position, an option position, and a
  second underlying. The dev account is flat, so the recording is `[]`, and the
  single most dangerous mistake this module could make is invisible against an
  empty list: **counting a short call contract as `-1` shares**, which makes a
  naked short look covered by arithmetic. GB-D-09 exists because of this file.
* **`calendar_halfday.HAND.json`** — Thanksgiving week 2026: a holiday the
  calendar omits entirely and a **13:00 half day** after it. 6c forbids a
  hand-rolled market calendar precisely because these are the days one gets
  wrong; this fixture is what proves the last close is read off the venue's
  calendar and not off a rule someone wrote down.

## Traps in the recorded data — read before changing a threshold

1. **Contracts paginate nearest-expiry-first.** The recorded run is the 500 and
   505 calls across all five expiries in the DTE band, and it comes back sorted by
   **expiry, then strike** — so page 1 is Sep 25 / Sep 30 / Oct 2 and page 2 is
   Oct 9 / Oct 16. The quirk is therefore visible *across the page boundary*,
   which is the point: a caller that omits `expiration_date_gte`/`lte` gets the
   front expiry whatever it asked for, and a caller that filters but stops at page
   one gets the near end of its own window. Both look like a thin chain, not like
   a bug. GB-D-F01 asserts the ordering; GB-D-01/02/03 assert the fetcher's half.

   The recording is deliberately narrowed (`type=call`, a two-strike band, page
   size 6 over 10 contracts) so the run **terminates**: page 2 carries a null
   token. A "two-page" sample that is really two pages of a longer run cannot
   prove that a fetcher stops, and the recorder now aborts rather than write one.
   The narrowing parameters are marked `fixture_*` in
   `config/datafeed.PROPOSED.json` and never reach a live run.
2. **Numerics are strings on `/v2/options/contracts` and `/v2/account`**
   (`"strike_price": "500"`, `"cash": "100000"`) and **numbers on the snapshots
   feed** (`"bp": 224.84`). Anything comparing across the two without casting is
   silently wrong.
3. **`greeks` is `null` on deep-ITM strikes** — three of the ten recorded
   snapshots have it, unprompted. This is the documented free-tier behaviour (CLAUDE.md),
   it arrived in a real recording rather than being staged, and it is why the
   screener must fail closed rather than guess.
4. **`open_interest` and `close_price` are `null` on strikes that have not
   traded.** Present as keys, null as values.
5. **The recorded quote timestamps are the previous session's close**
   (`2026-09-01T19:59:59Z`), because the recording was made before the open. Aged
   against wall-clock time they are ~16 hours stale and every contract would be
   rejected; aged against the 6c `as_of` — the last close, `2026-09-01T20:00:00Z`
   — they are 0.1 seconds old. That is the whole point of 6c, visible in one
   subtraction.

## Scrubbing

`scripts/record_fixtures.py` serializes every body and **scans it for the live
key and secret before writing**; a hit aborts the run and writes nothing. Request
headers are never recorded at all.

`account_number` is dropped. **The account `id` is deliberately kept**: it is not
a credential, the submission needs an account id, and a recording that cannot
name its account is a recording of nothing. GB-D-F03 and GB-D-F06 hold both
halves of that rule.
