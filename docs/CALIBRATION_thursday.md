# CALIBRATION — for the morning of 2026-09-03, before 13:30 UTC

**Nothing in this document has been applied.** No config file was modified by the
work that produced it. It exists so that teakeycee can decide, with evidence, what
if anything to change before the scored session starts — and the recommendation
it reaches is **change nothing**, which is a conclusion the numbers below are
meant to let you disagree with rather than a preference.

**One thing WAS changed, and it is code, not calibration:** commit `3c62069`,
*Runner: resolve as_of after the read (GB-R-18)*. Section 2 is the evidence for
it. If you want it out, `git revert 3c62069` restores the previous behaviour and
GB-R-18 is the test that will then fail.

## Method, and what it is not

Two captures against the **DEV** account `PA34K04ZYHYO`, `--no-submit`
throughout. **No order was sent and the scored account was never touched.**

| | cycles | window (UTC) | code |
|---|---|---|---|
| **Before** | 10 at 60s | 15:57:33 → 16:06:48 | `63f798d` (as_of resolved before the read) |
| **After** | 8 at 60s | 16:07:02 → 16:13:23 | `3c62069` (as_of resolved after the read) |

Raw records: `data/calibration_20260902.jsonl` and
`data/calibration_20260902_afterfix.jsonl` (gitignored — they hold account
balances). Regenerate the tables with
`python scripts/summarize_calibration.py <file>`.

`scripts/calibrate.py` attaches a **measurement-only observer** to the real
`run_cycle`, so every number here is the cycle's own contracts, its own snapshot
bodies, its own screener result and its own candidates. It is not a
re-implementation of the funnel; measuring the funnel with a second copy of the
funnel measures the copy.

**What this is not.** Sixteen minutes on one afternoon, ending 1h47m before the
close, on a chain of 0-DTE and 1-DTE SPY contracts. It says what the funnel did
in that window. It does not say what the 13:30–14:30 chain looks like, and no
number below should be treated as a calibration in the sense the config files
mean it. Everything still marked PROPOSED is still PROPOSED.

## 1. The chain, which is the same every cycle

| | value |
|---|---|
| contracts fetched | **692**, every cycle, over 7 pages |
| by expiry | 330 × 2026-09-02 (0 DTE), 362 × 2026-09-03 (1 DTE) |
| spot (SPY, IEX equities midpoint) | 765.28 – 765.94 |
| within 3% of spot | **184**, every cycle (strikes ≈ 742.7 – 788.7) |

Two rejection counts are **structural** — near-identical in all eighteen cycles,
before and after the fix, and untouched by any timing question:

| reason | all strikes | near the money (of 184) |
|---|---|---|
| `null_greeks` | 538 / 546 / 553 | 102 / 106 / 109 |
| `missing_bid` | **240 exactly, every cycle** | **24 exactly, every cycle** |

*(min / median / max across cycles.)*

**About 79% of this chain has incomplete greeks on the indicative feed, and 57%
of the near-the-money strikes do.** That is the real ceiling on the tradable
universe, it is the same before and after the fix, and **no threshold in
`thresholds.competition.json` touches it.** `require_complete_greeks` lives in
`tests/fixtures/thresholds.PROPOSED.json` and is `true`; turning it off is not on
the table, because the delta band is evaluated on a delta that would then not
exist — the screener would stop failing closed and the liquidity window would
start failing open. CLAUDE.md's line about this ("the screener must fail closed
on null greeks, never guess") is the rule, and it is the right one.

## 2. What was actually starving the funnel

### The symptom

Ten cycles before the fix. **Zero candidates. Zero. Across all ten.**

| cycle | accepted | `stale_quote` | of which negative-age | viable short legs | pairs | candidates |
|---|---|---|---|---|---|---|
| 0001 | 16 | 420 | **420** | 0 | 0 | 0 |
| 0002 | 20 | 552 | **552** | 0 | 0 | 0 |
| 0003 | 0 | 611 | **611** | 0 | 0 | 0 |
| 0004 | 14 | 346 | **346** | 0 | 0 | 0 |
| 0005 | 1 | 551 | **551** | 0 | 0 | 0 |
| 0006 | 15 | 605 | **605** | 0 | 0 | 0 |
| 0007 | 41 | 300 | **300** | 0 | 0 | 0 |
| 0008 | 3 | 481 | **481** | 0 | 0 | 0 |
| 0009 | 56 | 298 | **298** | 1 | 0 | 0 |
| 0010 | 54 | 215 | **215** | 0 | 0 | 0 |

**Every single `stale_quote` rejection was a NEGATIVE age** — a quote timestamped
*after* the `as_of` the cycle claimed to be measured at. Not one contract in ten
cycles was rejected for being old.

### Why

`run_cycle` resolved `as_of` from the clock read at the **start** of the cycle,
then spent 1.4–2.6 seconds fetching seven pages of contracts and the snapshots.
Every quote that updated during that window was stamped after the cycle's own
`as_of`, and the screener rejects a quote it cannot reconcile with the read that
claims to precede it — **correctly**. So the cycle was discarding the *freshest*
quotes in the chain, which are exactly the ones worth trading.

`scripts/dry_run.py` has always re-read the clock after the fetch, and its
`stamped()` docstring describes this failure precisely: *"a run that stamps
`as_of` up front is claiming a timestamp that precedes quotes it is holding …
Off-hours this changes nothing; inside a session it is the difference between
screening a chain and rejecting all of it."* The cycle runner, written yesterday,
did not. That is the whole defect.

### The two counterfactuals, computed per contract on each cycle's own quotes

Both count contracts that would clear the **whole** screener, not just the
freshness test — a contract with null greeks is not admitted by any amount of
patience, and a number that pretended otherwise would be the wrong number.

**A — a different `quote_max_age_seconds`** (before the fix):

| max_age | admitted, all | admitted, near the money |
|---|---|---|
| 60 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 300 s **(in force)** | 0 / 16 / 56 | 0 / 5 / 30 |
| 900 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 1 800 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 3 600 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 7 200 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 21 600 s | 0 / 16 / 56 | 0 / 5 / 30 |
| 86 400 s | 0 / 16 / 56 | 0 / 5 / 30 |

**Perfectly flat across four orders of magnitude.** Raising the threshold to a
full day would have admitted not one additional contract. This is the direct
answer to *"what `quote_max_age_seconds` would admit the actively quoted
near-the-money strikes"*: **no value of it would.** The threshold was never the
constraint, and tuning it before the bell would have been a whole morning spent
on a number that does nothing.

**B — stamping `as_of` when the read FINISHED** (same 300 s threshold, every age
shifted by +d):

| as_of shift | admitted, all | admitted, near the money |
|---|---|---|
| +0 s | 0 / 16 / 56 | 0 / 5 / 30 |
| +1 s | 84 / 124 / 150 | 46 / 65 / 77 |
| **+2 s** | **139 / 146 / 153** | **75 / 78 / 82** |
| +3 s | 139 / 146 / 153 | 75 / 78 / 82 |
| +5 s | 139 / 146 / 153 | 75 / 78 / 82 |
| +30 s | 139 / 146 / 153 | 75 / 78 / 82 |

Two seconds. It plateaus at two seconds and never moves again — because two
seconds is how long the read takes, and past that there is nothing left to
recover.

### Confirmed against the live venue, not just arithmetic

Eight cycles after the fix:

| | before (10 cycles) | after (8 cycles) |
|---|---|---|
| negative-age quotes | 215 / 481 / 611 | **0 / 0 / 0** |
| `stale_quote` rejections | 215 / 481 / 611 | **reason absent entirely** |
| accepted | 0 / 16 / 56 | **140 / 146 / 154** |
| viable short legs | 0 / 0 / 1 | **6 / 6 / 7** |
| complete 5-wide pairs | 0 / 0 / 0 | **3 / 3 / 3** |
| **candidates built** | **0 over 10 cycles** | **1 on every one of 8 cycles** |
| governor verdict | — | **approved, 8 / 8** |

The candidate is `SPY260903P00763000 / SPY260903P00758000` on all eight cycles,
at a net credit of 0.75 – 0.84 — **the identical structure the scored account is
already holding** from this morning's two governed orders.

## 3. Quote ages near the money, now that they can be measured

`as_of` − `latestQuote.t`, in seconds, for the 184 strikes within 3% of spot.
After the fix every one of the 184 has a non-negative age, so this is the whole
near-the-money set and not a surviving subset. Per-cycle percentile, reported as
min / median / max **across** the eight cycles — pooling them would average over
eight different market moments and describe none of them.

| percentile | seconds |
|---|---|
| p0 | 0.10 / 0.15 / 0.22 |
| p10 | 0.12 / 0.51 / 0.68 |
| p25 | 0.50 / 0.85 / 1.08 |
| p50 | **0.74 / 1.14 / 1.49** |
| p75 | 0.97 / 1.48 / 1.72 |
| p90 | 1.05 / 2.01 / 5.03 |
| p95 | 1.11 / 2.02 / 6.04 |
| p100 | **1.70 / 2.91 / 13.49** |

**The near-the-money strikes on the indicative feed are quoted within about a
second, and the single worst observation in eight cycles was 13.5 seconds.**
Against the 300-second threshold in force that is a factor of **22 of headroom at
the very worst tick**, and about 260× at the median.

And the counterfactual after the fix is flat too — 140 / 146 / 154 admitted at
**every** value from 60 s to 86 400 s. Even a 60-second threshold would change
nothing.

## 4. Are the open-interest and delta bands starving candidates?

**No.** They are doing their job. After the fix the funnel narrows:

```
692 fetched
 →  146 accepted            (546 null greeks, 240 no bid — structural, §1)
 →   51 clear the OI floor (>= 500)
 →    7 also inside the delta band (0.15 - 0.35)
 →    6 clear every short-leg rule
 →    3 complete 5-wide pairs, wings and all
 →    1 candidate, governed and APPROVED, every cycle
```

Note `wing_excluded = 0` and `no_wing_at_width = 0` on every cycle: **the long
wing is never the constraint.** Every viable short leg has a tradable 5-wide wing
below it.

### What other settings would give (3 cycles, band sweep)

Complete 5-wide pairs, min / median / max:

| delta band | OI ≥ 100 | OI ≥ 250 | OI ≥ 500 | OI ≥ 1000 |
|---|---|---|---|---|
| 0.10 – 0.40 | 7 / 7 / 7 | 7 / 7 / 7 | 6 / 6 / 6 | 1 / 1 / 1 |
| 0.12 – 0.38 | 6 / 6 / 7 | 6 / 6 / 7 | 5 / 5 / 6 | 1 / 1 / 1 |
| **0.15 – 0.35** | 4 / 4 / 4 | 4 / 4 / 4 | **3 / 3 / 3 ← in force** | 1 / 1 / 1 |
| 0.20 – 0.30 | 2 / 2 / 2 | 2 / 2 / 2 | 1 / 1 / 1 | 0 / 0 / 0 |

Read across: the settings in force sit in the middle of a smooth surface, not on a
cliff. They yield three pairs; the widest setting tried yields seven. **Every one
of these sixteen points except one produces at least one pair**, i.e. at least one
candidate per cycle. The only setting that produces nothing is 0.20–0.30 with an
OI floor of 1000, which is tighter than anything under consideration.

**A limitation, stated rather than buried:** the grid widens the band
symmetrically, so it cannot separate the effect of the lower bound from the
upper. That matters, because the two are not the same risk. Lowering
`short_leg_abs_delta_min` (0.15 → 0.12) admits short legs **further** from the
money — less premium, lower assignment probability, more conservative. Raising
`short_leg_abs_delta_max` (0.35 → 0.40) admits short legs **closer** to the money
— more premium and more risk. If you want to move only one, move the minimum.

## 5. PROPOSED revision to `config/thresholds.competition.json`

### The proposal is: **no change. Apply nothing.**

```diff
  (no diff)
```

Every number in that file, with the evidence beside it:

| key | in force | evidence | proposal |
|---|---|---|---|
| `max_loss_cap.vertical_spread` | 2% of equity | not reached; the sized candidate was 1 lot at ≈420 against a 2 000 cap | **keep** |
| `max_loss_cap.cash_secured_put` | 2% of equity | not exercised this capture | **keep** |
| `max_loss_cap.covered_call` | `null` | 2e: no standalone figure exists | **keep** |
| `x_total_open_risk` | 10% of equity | not reached; book never exceeded one lot | **keep** |
| `net_reconcile_tolerance` | 0.005 | every candidate reconciled exactly | **keep** |
| `cash_floor_pct` | 0.20 | not reached | **keep** |
| `churn_window_seconds` | 3600 | not exercised (no fills; `--no-submit`) | **keep** |
| `min_hold_seconds` | 7200 | not exercised | **keep** |
| `position_caps` | 4 / 2 | not reached | **keep** |
| `max_expiry_date` | 2026-09-03 | DECIDED; every candidate expires inside it | **keep — frozen** |
| `liquidity_window.require_two_sided_quote` | `true` | `missing_bid` is a stable 240; relaxing it would propose un-executable legs | **keep** |
| `liquidity_window.min_open_interest` | 500 | §4: yields 3 pairs; 250 would yield 4 | **keep** |
| `liquidity_window.short_leg_abs_delta_min` | 0.15 | §4: yields 3 pairs; 0.12 would yield 5–6 | **keep** |
| `liquidity_window.short_leg_abs_delta_max` | 0.35 | §4: raising it moves the short leg toward the money | **keep** |

**Why nothing.** The funnel now produces a governed, approved candidate on every
cycle at the settings in force, on the same structure the account already holds.
The config's own `_status` says everything but the three DECIDED numbers is
uncalibrated and inherited, and sixteen minutes of one afternoon is not a
calibration. Changing a threshold now would also change the file's content hash,
which is the `config_version` recorded on every scored verdict — and this
morning's two live orders name the current hash
(`sha256:0066384c…`). That is a real cost to set against a benefit the evidence
does not show.

### If you decide you want more candidate flow anyway

Ranked by how little they change about *where the position sits*, with what the
sweep says each buys. **Any of these is your call, applied before 13:30 UTC,
never mid-session.**

1. **`min_open_interest` 500 → 250.** Pairs 3 → 4. Does not move the short leg
   relative to spot at all; it only accepts thinner strikes. Lowest-risk lever
   here, smallest gain.
2. **`short_leg_abs_delta_min` 0.15 → 0.12.** Pairs 3 → ~5 (from the 0.12–0.38 row
   at OI 500; the grid cannot separate this from the upper bound moving too, so
   treat it as an upper estimate). Admits short legs **further out of the money**
   — less premium per lot, lower assignment probability. Conservative in
   direction, and it is where most of the sweep's gain comes from.
3. **Both of the above** — the 0.12–0.38 / OI 250 cell: pairs 3 → 6–7.
4. **`short_leg_abs_delta_max` 0.35 → 0.40.** Recommended **against**. It moves
   the short leg toward the money on a 1-DTE position judged at Thursday's close.
   The extra premium is real and so is the extra assignment risk, and the sweep
   cannot tell you how much of the gain in rows 1–3 came from this side.

Whatever you choose, `pytest -q` must stay green afterwards: **GB-C-F08 asserts,
key by key, that everything except the three DECIDED numbers is inherited verbatim
from `tests/fixtures/governor/thresholds.governor.PROPOSED.json`.** If you change
a `liquidity_window` value it will fail, correctly, and the honest fix is to
update that criterion in the same commit with the reason attached — not to relax
it.

## 6. What to watch for on Thursday

- **`read=` on the log line** is new: how long the chain took to come back, and
  therefore the window during which a quote can arrive and still reconcile. It ran
  **1.4 – 2.6 s** here. If it climbs into the tens of seconds, the venue is slow
  and the funnel will narrow again — the mechanism is understood now, and it is
  `screen_rejects=stale_quote:*` reappearing that would tell you.
- **`screen_rejects=null_greeks:~546`** is normal and structural. It is not a
  problem to solve at 14:00.
- **`stale_quote` should be at or near zero.** If it is large, something has
  regressed to the pre-`3c62069` behaviour, and no threshold will fix it.
- **The capture window ended at 16:13 UTC, 1h47m before the close.** The
  13:30–14:30 chain is not measured here. `scripts/calibrate.py --env .env
  --cycles 3 --interval 60` re-runs the whole measurement against DEV in three
  minutes and writes nothing to the scored account — if the morning looks
  different from this, that is how to find out before starting the session.
