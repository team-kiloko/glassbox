# Chain-screener golden fixtures

Hand-built, **synthetic** fixtures for the GlassBox chain screener. They reproduce
the *shapes* Jhoosier verified on the free paper tier (HANDOFF 2026-08-30 15:00 UTC,
verification gate (c)); the *values* are invented to be plausible, not captured live.
No live capture is claimed and no account data appears here.

Underlying: SPY, spot ~640.12. Expiry: 2026-09-18 (monthly, third Friday), 21 DTE.
Snapshot `as_of`: **2026-08-28T19:55:00Z** (Friday, 15:55 ET — five minutes before close).

## Files

| File | Stands in for |
|------|---------------|
| `contracts_spy_2026-09-18.json` | `GET /v2/options/contracts` |
| `snapshots_spy_2026-09-18.json` | `GET /v1beta1/options/snapshots/SPY?feed=indicative` |
| `thresholds.PROPOSED.json` | the screener config the fixtures were built against — **PROPOSED, uncalibrated** |
| `expected_verdicts.json` | the golden accept/reject outcome per symbol |

## The slice: 8 contracts, 2 accept, 6 reject

| Symbol | Case | Greeks | Quote | Age vs `as_of` | Expected |
|--------|------|--------|-------|----------------|----------|
| `SPY260918C00640000` | healthy ATM call | complete | 8.82 x 8.94, two-sided | 1 s | **accept** |
| `SPY260918P00635000` | healthy NTM put | complete | 6.31 x 6.42, two-sided | 3 s | **accept** |
| `SPY260918C00500000` | deep ITM (140 pts) | **null** | 139.85 x 140.95, wide/thin | 79 s | reject `null_greeks` |
| `SPY260918C00780000` | illiquid far OTM | **null** | **no bid**, 0.02 ask | 163 s | reject `null_greeks`, `missing_bid` |
| `SPY260918P00470000` | deep OTM put | complete | **no bid**, 0.03 ask | 47 s | reject `missing_bid` |
| `SPY260918C00655000` | **stale** | complete | 3.41 x 3.49, looks healthy | **8208 s** | reject `stale_quote` |
| `SPY260918C00700000` | **absent from snapshots** | — | — | — | reject `no_snapshot` |
| `SPY260918C00760000` | far OTM, offer pulled | complete | 0.04 bid, **no ask** | 25 s | reject `missing_ask` |

Each rejection isolates one defect, except `C00780000`, which carries both by
design (the HANDOFF quirk note pairs null greeks with illiquid strikes).

## Traps these fixtures exist to catch

1. **`bp: 0, bs: 0` is a MISSING bid, not a $0.00 price.** Alpaca represents "no bid"
   this way rather than omitting the field. A screener that reads `bp` as a number
   and proceeds will price a spread off a bid that does not exist. `P00470000`
   isolates this: its greeks are complete and its quote is fresh, so `missing_bid`
   is the *only* thing standing between it and acceptance.
2. **`ap: 0, as: 0` is a MISSING ask, and it needs its OWN code.** The mirror of
   trap 1, and not mere symmetry: `thresholds.PROPOSED.json` requires a *two-sided*
   quote, and a vertical **buys** a leg, so an absent offer is un-executable on the
   long side. `C00760000` isolates this — complete greeks, fresh quote, a real
   0.04 bid — so `missing_ask` is the *only* thing standing between it and
   acceptance. Rejecting it as `missing_bid` is a mislabel, and accepting it
   because "there's a quote" is the bug.
3. **A stale quote looks perfectly healthy field-by-field.** `C00655000` has complete
   greeks and a tight two-sided quote. Only the timestamp betrays it. Freshness must
   be checked against `as_of`, never against wall-clock at read time.
4. **Null greeks are `null`, not zero and not absent.** `greeks: null` with
   `impliedVolatility: null` alongside. Do not conflate with a greek that is
   legitimately ~0 (see `P00470000`, `gamma: 0.0001`).
5. **A contract can exist with no snapshot at all.** The snapshots endpoint may omit
   symbols. Absence is a reject, not a skip and not a retry-until-present.
6. **Numerics are STRINGS on the contracts endpoint** (`strike_price`, `open_interest`,
   `multiplier`, `close_price`) and **floats on the snapshots endpoint**. Anything
   comparing a strike across the two without a cast is silently wrong.
7. **Timestamps are RFC3339 with nanosecond precision.** Python's `datetime` parses
   at microsecond resolution; truncate deliberately rather than letting a parser fail.

## Not covered here (deliberate)

- **Pagination.** The contracts endpoint paginates nearest-expiry-first and is filtered
  with `expiration_date_gte`/`lte` (HANDOFF quirk). The `next_page_token` field is
  present and `null`; a multi-page fixture is a separate exercise.
- Condition codes (`c`) and exchange codes (`ax`/`bx`) are populated for realism only.
  Nothing in the suite asserts on them, and the screener should not depend on them.
- Open-interest and volume floors. Those are calibration decisions, not fail-closed
  correctness, so no threshold for them is proposed yet.

## Reason-code vocabulary — the seam is the authority

The five codes `null_greeks | missing_bid | missing_ask | stale_quote |
no_snapshot` are **`DECIDED (2026-09-02)` in `GB_INTERFACES.md` shape 6**, which is
SIGNED and IN FORCE. These fixtures **mirror** the seam; they never define it. If
the two ever disagree, the seam wins and the fixtures are the thing that is wrong.

The sign-off commit left a known gap — the seam named five codes while
`expected_verdicts.json` named four, because the `missing_ask` counter-fixture was
teakeycee's to land as screener lead. **That gap is closed as of this commit:** the
fixture (`C00760000`), the golden verdict, and GB-S-13 are here, and
`expected_verdicts.json` now names all five. The seam's own "Not yet in the
fixtures" note under shape 6 is therefore stale, but the seam changes only by both
humans' agreement — it is flagged in HANDOFF, not edited here.

## Status

`thresholds.PROPOSED.json` is **uncalibrated**. `quote_max_age_seconds: 300` is a
placeholder chosen so the stale case sits unambiguously outside it and every fresh
case unambiguously inside — it is not a trading judgement. The screener's real config
must supersede it before anything trades.
