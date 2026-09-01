# Sign-off review - teakeycee positions (2026-09-01)

Companion to docs/signoff_agenda.md. Format: position + one-line why.
Three FINDINGS first; they change items A4, A6, and the reason vocabulary.

## Findings from the draft review

**F1 (structural, affects A4): the id-first scheme forces option (c).**
Shape 4 requires the ledger entry to be written BEFORE submission so
client_order_id can embed its id. Shape 5 makes entries append-only and puts
order/fill inside the entry. Those three cannot all hold: the fill arrives
after the entry exists, and recording it in the same entry is mutation.
So in-flight handling is not a free choice: (a) and (b) contradict the
draft's own id scheme or its append-only rule. Adopt (c): the decision
entry is written pre-submission with order/fill null; submission, fill, or
broker rejection are appended follow-up entries referencing the root id;
add `submitted` to the vocabulary for the in-flight append; the dashboard
folds chains by root id. This also makes partial fills honest: Alpaca's
partially_filled is non-terminal, so terminal-only vocabularies misfile it.

**F2 (silent-corruption risk, affects A6): pin the UNITS, not just the sign.**
The sign convention (positive = debit) is fine, but net_debit_credit has a
second silent-corruption axis the draft doesn't pin: per-share (broker
quoting convention, x100 multiplier applied downstream) vs total dollars.
A governor computing max loss with the wrong assumption is off by 100x in
whichever direction. Position: per-share, matching how options are quoted
and how Alpaca's net limit is expressed, with the multiplier explicit in
governor math and the reconciliation rule restated as per-share sums.
Also: verify the sign convention against Alpaca's actual mleg wire format
before signing (docs, .md trick) so seam and wire match 1:1 with no
translation layer.

**F3 (the fifth reason code exists): `missing_ask`.**
thresholds.PROPOSED.json requires a TWO-SIDED quote, but the vocabulary
only has missing_bid. A contract with bid but no ask must be rejected
(two-sided rule) yet has no code to reject WITH, violating GB-S-06's
machine-readable-reason guarantee or forcing a mislabel. Add missing_ask
plus one counter-fixture (greeks complete, fresh, bid present, ask absent).
Matters beyond symmetry: verticals BUY a leg; a missing ask is
un-executable on the long side.

## A items

- **A1 iron condor: Option B (two composed verticals).** No special-case
  max-loss math, matches the settled scope literally, drops iron_condor
  from the enum (which also resolves the CLAUDE.md alignment note for
  free). The one-vertical-fills window is acceptable risk on paper for a
  hackathon; revisit for any future live system. Time-boxed build favors B.
- **A2 reservations: (b) governor-from-ledger.** The component that owns
  risk owns "this collateral is spoken for"; the data layer stays a dumb,
  honest reporter of broker state (its job is honesty, not judgment). Also
  more demoable: the ledger literally drives the coverage story.
- **A3 checks[] vocabulary: hybrid.** Pin a minimal core in the seam
  (structure_valid, net_reconciles, max_loss_cap, coverage, cash_floor,
  churn_guard, market_open) since the dashboard and write-up will name
  them and renames mid-crunch break the demo; governor lead may add
  extras under an x_ prefix without a seam change.
- **A4: (c), per Finding F1.** Not preference; forced by the draft's own
  id scheme + append-only rule.
- **A5 as_of policy: (a) as proposed, plus one governor check.** Open ->
  now; closed -> last close via /v2/clock + /v2/calendar, no hand-rolled
  calendar. Mitigate the "freshness does no work off-hours" concern by
  adding market_open to the governor's checks: screening and proposing
  run any time (demos, dry runs), but ORDER SUBMISSION requires the
  market open. Safety lives in the governor, where it belongs, and the
  scored account can still trade first thing at open.
- **A6: agree convention, per Finding F2 pin units + verify wire format.**
- **A7 content-hash config_version: agree.** Hand-bumped versions drift.
- **A8 client_order_id scheme: agree.** Broker idempotency is exactly
  what a scored account needs.
- **A9 claimed_* advisory: agree.** The rename is the audit story in
  miniature; the false-claim GB-C fixture stays.
- **A10 nullable order/fill, append-only: agree,** as modified by F1(c).
- **A11 no file I/O in screen_chain: agree.** GB-S-10 requires it.

## B items

- **B1 initial leads, proposal:** teakeycee: chain screener, governor +
  contract suites, provenance ledger, strategist prompt review
  (adversarial). Jhoosier: data layer (he live-tested the endpoints), MCP
  executor, LLM backend + strategist, NL intent UX, dashboard, video/deck.
  Telegram digest: propose marking OPTIONAL/stretch at sign-off; three
  build days argue for cutting it unless it's nearly free. Leads rotate
  freely afterward per protocol.
- **B2 demo platform: Jhoosier's call.** Note Streamlit pairs naturally
  with a Python ledger if he wants the path of least resistance.
- **B3 competition account: create TODAY (Monday), separately from
  first trade.** Creation is cheap and unblocking: fresh signup on the
  bare team address (owner: Jhoosier, who holds the team email), Level 3
  options enabled AT CREATION per his own links-doc flag, $100k balance,
  ID into HANDOFF + SUBMISSION.md, keys to the sheet. First order waits
  for the pipeline to pass GB-S + GB-C regardless; decoupling creation
  from trading means account setup never blocks a ready agent. Target
  first governed trade Tue Sep 1 open... [correction: today IS Sep 1;
  target first governed trade Wed Sep 2 pre-freeze, or today if the
  governor lands and passes].
- **B4: same as A5.**

## After signing (order of work, teakeycee side)

1. Screener module (arms the 12 GB-S tests; smallest module, biggest
   test payoff) with missing_ask added per F3.
2. GB-C governor contract suite + governor (the deep one: reconciliation,
   independent max loss incl. the false-claim fixture, coverage vs account
   state, market_open, caps).
3. Ledger writer with F1(c) append-chain semantics.
