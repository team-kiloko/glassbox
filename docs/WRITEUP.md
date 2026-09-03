# GlassBox — one-page write-up

**Agentic, but auditable.** GlassBox is an autonomous options agent whose every
order passes a deterministic risk governor, with an append-only provenance
ledger that replays any decision from its own recorded inputs. Paper trading
only, on the dedicated competition account `PA3424LCNZBS`. Every figure below
is read from the repo: `GB_INTERFACES.md`, `glassbox/governor.py`,
`config/thresholds.competition.json`, `HANDOFF.md`.

## AI logic

The pipeline is **chain screen → candidates → governor verdict → order → ledger**,
run unattended by `scripts/run_session.py` on a 900-second cycle. Each cycle
fetches the full SPY chain, screens it, builds ranked defined-risk candidates,
governs them, and submits at most one order.

The strategist seam is one function, `build_candidates`, which receives the
screened contracts and returns proposals in the seam's shape 2. Alpaca's MCP
server belongs in that natural-language path, where a model reasons about the
market; the rules-based builder that produced the scored run's proposals is a
drop-in stand-in for it. Nothing downstream cares which produced a proposal:
the governor recomputes every number it is handed, and the ledger records
`prompt_version` (null on the scored run: no language model wrote that
proposal) so an auditor can tell.

The screener **fails closed**: null greeks, a missing bid or ask, a missing
snapshot or a stale quote is a rejection with a machine-readable reason, never a
guess. Freshness is measured against a passed-in `as_of`, never a wall clock,
so identical inputs give identical verdicts.

## Risk gates

Scope is **defined-risk only, and the order builder cannot express a naked
short.** The two single-leg builders take the covering asset as a required
argument with no default; there is no general single-leg builder to reach for.
Iron condors exist only as two governed verticals.

The governor is pure: no I/O, no clock, thresholds passed in by the caller and
identified by the content hash of the config file. It emits ten checks per
decision. The seven seam-pinned core checks are `structure_valid`,
`net_reconciles`, `max_loss_cap`, `coverage`, `cash_floor`, `churn_guard` and
`market_open`; three extensions are `x_position_cap`, `x_max_expiry` and
`x_total_open_risk`. **The governor recomputes max loss from strikes, ratio,
quantity and net price, and reads the proposal's claim only to record the
divergence.** The scored ledger holds the proof: a deliberately oversized
cash-secured put claimed a max loss of 250.00; the governor computed 152,584.00
against a 2,000.00 cap and refused it on four checks, writing the 152,334.00
divergence into the record.

Scored-run thresholds, decided by teakeycee and frozen for the event: per-structure
max loss 2% of equity, total open risk across the book 10% of equity, a 20%
cash floor, a 3,600-second churn window, a 7,200-second minimum hold, at most
four open positions and two per underlying, and every leg expiring on or before
2026-09-03 so positions resolve inside the scored window. Sizing asks the
governor rather than computing a cap a second time. Positions are 763/758 SPY
put verticals, five lots, total computed max loss 2,067.00 on a 10,000.00 book
cap.

The ledger is append-only: a root decision entry is written before submission,
follow-ups chain on its id, corrections are new entries. `replay_root`
re-derives any verdict from the entry's embedded proposal, account state and
clock under the config it names; the audit dashboard exposes that as a button.
Seven contract suites are the merge gate: 189 tests pass.

## Alpaca infrastructure

Data comes from Alpaca's free paper tier through an injectable-transport data
layer: `/v2/options/contracts` paginated to exhaustion (it serves
nearest-expiry-first), `/v1beta1/options/snapshots` on the indicative feed,
`/v2/clock` and `/v2/calendar` for the off-hours `as_of` policy with no
hand-rolled calendar, and `/v2/account` for raw balances. The trading base URL
must contain `paper`, checked on every request.

Execution goes through Alpaca's official `alpaca-py` SDK, pinned at 0.44.0,
for the reasons the event FAQ asks to be explained (`docs/EXECUTION_RATIONALE.md`):
determinism, contract-testability against a fake transport, and broker-side
idempotency. Verticals are `mleg` orders on a signed net limit; single-leg
structures carry a positive limit with direction from `side`. Every
`client_order_id` is the per-box prefix plus the root ledger entry id, so a
retried submission is refused as a duplicate. Before building any payload the
executor reads `/v2/account` over the same connection and refuses unless the
account number is the one the run was authorised for, so the shared dev account
and the scored account cannot be confused.
