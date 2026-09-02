# Governor golden fixtures (GB-C)

Hand-built, **synthetic** fixtures for the GlassBox governor — the highest-value
module in the system and the one that gets the deepest suite (SETUP.md Phase 4.4).
No live capture is claimed and no account data appears here.

Underlying SPY, spot ~640, expiry 2026-09-18. Reference `as_of` is the **clock**
fixture's `timestamp`: `2026-09-02T15:30:00Z` open, `2026-09-02T01:00:00Z` closed.

## Files

| File | Stands in for |
|------|---------------|
| `thresholds.governor.PROPOSED.json` | the governor config — **PROPOSED, uncalibrated** |
| `proposals.json` | strategy proposals, seam shape 2 |
| `account_states.json` | account state, seam shape 2b (raw **and** composed) |
| `clocks.json` | `GET /v2/clock`, for `market_open` (6c) |
| `expected_verdicts.json` | the golden verdict per case, seam shape 3 |

## The 18 cases: 4 approve, 14 reject

Each rejection isolates one check wherever the arithmetic allows it. Where it does
not — an uncollateralised put necessarily breaches the cash floor too — the golden
file says so and the criterion asserts on the check it is about.

| Case | Fails | Point |
|------|-------|-------|
| `covered_call_approved` | — | fail-closed must not mean fail-everything |
| `cash_secured_put_approved` | — | 61590 computed max loss under a 62500 cap |
| `debit_vertical_approved` | — | carries `mode: autopilot`, to prove passthrough |
| `credit_vertical_approved` | — | `(width - credit)`, the other vertical branch |
| `iron_condor_rejected_out_of_enum` | `structure_valid` | A1 Option B: not in the enum |
| `lone_short_leg_rejected` | `structure_valid` | **the naked-short trap** |
| `ratio_gcd_rejected` | `structure_valid` | C2: `ratio_qty` GCD must be 1 |
| `net_mismatch_rejected` | `net_reconciles` | **the qty-factor trap** (C1) |
| `false_claim_rejected_by_computed_figure` | `max_loss_cap` | **the false-claim fixture** |
| `csp_over_cap_rejected` | `max_loss_cap` | CSP formula against its own cap |
| `covered_call_double_claim_rejected` | `coverage` | two calls, the same 100 shares |
| `csp_coverage_rejected` | `coverage`, `cash_floor` | unreserved cash, not gross cash |
| `vertical_buying_power_rejected` | `coverage` | buying power vs **computed** max loss |
| `cash_floor_rejected` | `cash_floor` | collateral fine, post-trade cash is not |
| `churn_window_rejected` | `churn_guard` | re-entry 600 s after the last open |
| `min_hold_rejected` | `churn_guard` | past the window, short of the min hold |
| `market_closed_rejected` | `market_open` | every other check still computed |
| `position_cap_rejected` | `x_position_cap` | a non-seam check on the `x_` prefix |

## Traps these fixtures exist to catch

1. **A claimed max loss is not a max loss.** `false_claim_debit_vertical` states
   `claimed_max_loss: 200` for a spread whose real figure is **819**. A governor
   that reads the field approves a trade over its own cap. The claim is ADVISORY
   (2d) and the divergence belongs in the verdict, not in the decision.
2. **`qty` is not a factor in the reconciliation.** `net_mismatch_qty_factor` is
   two units of a spread whose per-share net is 4.60, reporting **9.20**. The wire
   limit is per unit and independent of `qty` (C1). A governor that multiplies by
   `qty` here "reconciles" the wrong number and never notices.
3. **A lone short leg is a valid-looking vertical.** `lone_short_declared_vertical`
   has a legal `structure`, a legal leg, and arithmetic that reconciles. Only leg
   *composition* betrays it. This is 2e in fixture form: naked-short prevention is
   not a schema property.
4. **Reserved is not spent.** `composed_shares_fully_reserved` holds 100 shares and
   `composed_cash_short` holds 62000 in cash — both look sufficient until the
   reservations are subtracted. Coverage is about *unreserved* collateral.
5. **Coverage passing does not mean the trade is affordable.** `cash_floor_rejected`
   has the collateral and still breaches the floor. Two different questions.
6. **Two limits on one axis.** `churn_window_seconds` (3600) and `min_hold_seconds`
   (7200) are deliberately different so `min_hold_rejected` sits between them: past
   the churn window, short of the min hold. A governor that collapses them into one
   number passes a trade it should refuse.
7. **A closed market does not excuse the other checks.** `market_closed_rejected`
   expects a full `checks[]` — the verdict is an audit record, not an early exit.

## Two definitions this suite pins down

The seam names `cash_floor` and `churn_guard` in the pinned vocabulary (3a) but does
not define their arithmetic. These are the governor lead's definitions, **PROPOSED**
along with the numbers, and they are written here so the other pod can attack them:

**`cash_floor`.** Post-trade free cash must stay at or above
`cash_floor_pct * cash` (pre-trade raw broker cash):

```
free_cash_before = cash - reserved_cash
premium_flow     = -(net_debit_credit * 100 * qty)     credit positive, debit negative
collateral       = covered_call      -> 0              (shares are the collateral)
                   cash_secured_put  -> strike * 100 * qty
                   vertical (credit) -> width  * 100 * qty
                   vertical (debit)  -> 0              (the debit is already in premium_flow)
free_cash_after  = free_cash_before + premium_flow - collateral
```

For a CSP and for either vertical this reduces exactly to
`free_cash_before - computed_max_loss`; for a covered call it is
`free_cash_before + premium`. That identity is the check on the definition.

**`churn_guard`** reads two ledger-derived facts per underlying and fails on either:
`as_of - last_open_at < churn_window_seconds` (re-entry cooldown, counted from the
last opening order whether or not it filled), or
`as_of - position_opened_at < min_hold_seconds` (the open position on that
underlying is younger than the minimum hold).

## The `ledger` block — governor-derived, proposed for the seam

`composed_*` account states carry a **`ledger`** block that the seam's 2b composed
view does not yet print:

```json
"ledger": { "open_positions": { "SPY": 1 },
            "recent_activity": { "SPY": { "last_open_at": "iso-utc",
                                          "position_opened_at": "iso-utc|null" } } }
```

Same provenance as `reserved_cash` / `reserved_shares` under A2 (b): **derived by
the governor from the provenance ledger, never requested from or supplied by the
data layer.** `churn_guard` and `x_position_cap` cannot be computed without it, and
the governor's entry point takes no ledger argument. It does not cross the seam, so
it is not a data-layer contract change — but 2b prints the composed view, so
printing this block there is proposed to both humans in HANDOFF rather than
written in unilaterally.

## Raw vs composed account state

`raw_broker_state` is the **data layer's** output under A2 (b): no `reserved_cash`,
no `reserved_shares`, no `ledger`. Handing it to the governor is a **caller error**
and raises — it is not a rejection. Same division as the screener: data quality is
rejected with a reason, a schema violation raises rather than being laundered into a
verdict. A governor that silently read a raw state would treat every reservation as
zero and approve double-claims all day.

## Status

`thresholds.governor.PROPOSED.json` is **uncalibrated**. Every number in it —
caps, `cash_floor_pct`, both windows, the position caps — was chosen so each fixture
sits unambiguously on one side of its threshold. None of them is a trading
judgement, and the real config must supersede this file before anything trades.
