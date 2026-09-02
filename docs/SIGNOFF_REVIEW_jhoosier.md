# Sign-off review - Jhoosier positions (2026-09-02)

Companion to docs/signoff_agenda.md and docs/SIGNOFF_REVIEW_teakeycee.md.
Format: position + one-line why. Where we agree, the item is READY TO SIGN.
Four amendments come out of the F2 wire check (docs/F2_wire_check.md); they
are the only new material.

## Findings

**F1 (A4 forced to (c)): accept.** The argument is sound: the id must exist
before submission, the fill arrives after, append-only forbids the write-back.
Adopt (c). Add `submitted` to the vocabulary. Root entry = decision entry
(order/fill null); follow-ups reference `root_id`; the dashboard folds by
root. Add `partial_fill` as a non-terminal follow-up, not a terminal state.

**F2 (units + wire format): accept, verified, with four amendments.**
Checked against Alpaca's SDK reference and Level 3 guide (sources in
docs/F2_wire_check.md). Sign convention matches the wire: positive = debit,
negative = credit. Units are per-share: the mleg `limit_price` is the net for
ONE unit of the spread; multiplier (100) and order qty are applied
downstream. Amendments to the draft, all in §2c/§4:

- C1. Reconciliation rule must NOT multiply by proposal qty. Restate as
  `net_debit_credit = sum(sign(action) * limit_price * ratio_qty)` per share,
  buys positive, sells negative. Dollar exposure = net * 100 * qty, computed
  by the governor, never carried in the proposal.
- C2. Legs carry `ratio_qty` (integers, GCD 1); `qty` moves to the proposal
  level. Mirrors the wire; GCD=1 becomes part of `structure_valid`.
- C3. Covered call and cash-secured put are single-leg option orders, not
  mleg (mleg needs 2+ legs). Wire limit_price on a single leg is always
  positive; direction comes from `side`. The executor's single-leg
  constructors send `limit_price = abs(net)`, `side` from action. Written
  into §4 so nobody submits a negative limit on a single leg.
- C4. Order shape (§4) gains `position_intent` per leg. Opening only for
  this event: buy -> buy_to_open, sell -> sell_to_open.

**F3 (`missing_ask`): accept.** Two-sided rule with a one-sided vocabulary is
a hole. Add `missing_ask` to shape 6 and one counter-fixture (greeks
complete, fresh, bid present, ask absent). Screener lead (teakeycee) owns
the fixture.

## A items

- A1 iron condor: **agree, Option B.** `iron_condor` leaves the enum;
  composition is a strategist concept. CLAUDE.md build-rules line gets
  updated to "iron condors are two vertical_spread proposals" at the swap.
- A2 reservations: **agree, (b) governor-from-ledger.** Data layer stays a
  dumb reporter of broker state. Note for my data-layer build: shape 2b
  then drops `reserved_cash` / `reserved_shares` from the data layer's
  output; they live in the governor's ledger-derived view.
- A3 checks[]: **agree, hybrid.** Pinned core: structure_valid,
  net_reconciles, max_loss_cap, coverage, cash_floor, churn_guard,
  market_open. Extras under `x_`. Dashboard renders the core by name and
  any `x_` generically.
- A4: **agree, (c).** Per F1.
- A5 as_of: **agree, (a) + market_open governor check.** Screening and
  proposing run any time; submission requires the market open per
  /v2/clock. Data layer (mine) exposes `clock()` and `calendar()` pass-
  throughs so nobody hand-rolls a calendar.
- A6: **agree,** verified; see F2 amendments C1-C4.
- A7 content-hash config_version: **agree.**
- A8 client_order_id scheme: **agree.**
- A9 claimed_* advisory: **agree.**
- A10 nullable order/fill, append-only: **agree,** as modified by F1(c).
- A11 no file I/O in screen_chain: **agree.**

## B items

- B1 initial leads: **accept teakeycee's split as proposed.**
  teakeycee: chain screener, governor + contract suites, provenance ledger,
  strategist prompt review (adversarial).
  Jhoosier: data layer, order builder / executor (Alpaca MCP), LLM backend,
  strategist, NL intent UX, dashboard, video + deck.
  **Telegram digest: OPTIONAL / stretch.** Not on the critical path; built
  only if the dashboard lands with time to spare. Leads rotate via HANDOFF.
- B2 demo platform: **Streamlit.** Python end to end, reads the ledger
  directly, Streamlit Community Cloud gives a public URL from the repo.
  Account being created 2026-09-02.
- B3 competition account: **Jhoosier creating 2026-09-02** on the bare team
  address, Level 3 at creation, $100k. ID to HANDOFF + SUBMISSION.md, keys
  to the vault in a separate entry from the dev keys. No manual orders.
  First governed trade: as soon as GB-S + GB-C pass, target 2026-09-02 US
  open or the next open after.
- B4: same as A5.

## Ready to sign

With F1(c), F2 C1-C4, F3, A1 Option B, A3 hybrid, A5 (a)+market_open, and
B1-B3 above folded into the draft, Jhoosier signs. teakeycee: confirm
C1-C4 (they are wire-format facts, not preferences) and sign in the change
log; then Jay performs the swap over GB_INTERFACES.md.

## After signing (order of work, Jhoosier side)

1. Data layer: account, positions, open orders, clock/calendar, contracts
   (expiration filter), snapshots (fail closed on null greeks). Contract
   tests with recorded fixtures.
2. Order builder / executor: structure-tagged constructors (single-leg for
   CC/CSP, mleg for verticals), client_order_id from ORDER_ID_PREFIX,
   position_intent, abs() rule for single legs. Cannot express a naked
   short.
3. Strategist + LLM backend + NL intent path.
4. Streamlit dashboard reading the ledger; governor rejection replay is the
   hero view.
5. Video + deck + one-page write-up.
