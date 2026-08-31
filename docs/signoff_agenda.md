# Sign-off agenda — GlassBox Phase 4 touchpoint

One page. Every decision that needs both humans, one line each: decision +
options. Run down it fast.

**Inputs:** `GB_INTERFACES.SIGNOFF-DRAFT.md` (the draft under review — the frozen
`GB_INTERFACES.md` stays the file of record until both sign), SETUP.md Phase 4,
HANDOFF 2026-08-30 22:07 UTC (teakeycee's Attack-next).

**Output:** both signatures on the draft, initial leads declared in a HANDOFF
block, then a human swaps the draft in over `GB_INTERFACES.md`.

---

## A. Shape decisions (all `OPEN (sign-off):` markers in the draft)

| # | Decision | Options | Why it matters | Draft § |
|---|----------|---------|----------------|---------|
| A1 | **Iron condor representation** | (a) one 4-leg `iron_condor` proposal; (b) two composed `vertical_spread` proposals | Max-loss math (risk = one wing, not two), order count at the broker, ledger shape (one entry vs. two linked); under (b), `iron_condor` leaves the enum | 2a |
| A2 | **Reservation producer for account state** | (a) data layer computes `reserved_cash` / `reserved_shares` from open orders + positions; (b) governor maintains them from the ledger | Field names are the same either way; decides which component owns "this collateral is already spoken for" | 2b |
| A3 | **`checks[]` rule vocabulary** | (a) pin the rule names in the seam; (b) leave to the governor lead | Pinning keeps the dashboard + GB-C suite stable across rule renames; leaving open lets the governor lead add checks without a seam change | 3 |
| A4 | **Ledger `status` in flight** | (a) terminal-only, no status until settled; (b) status advances in place; (c) each transition is a new appended entry referencing the prior id | (b) collides with the append-only rule; also decides whether `submitted` / `pending` join the vocabulary | 5 |
| A5 | **Caller `as_of` policy** (teakeycee's flagged design question) | (a) proposed: open → `now`, closed → last close via Alpaca `/v2/clock` + `/v2/calendar`, no hand-rolled calendars; (b) market-hours-only screening | Affects **run scheduling** and the **scored P&L window**. Any quote is hours old outside market hours, so a naive freshness rule rejects everything on a weekend | 6c |

### Confirm-in-passing (proposed in the draft; object now or they stand)

- **A6 — `net_debit_credit` sign convention:** positive = net debit paid, negative = net credit received. Object if either pod's code reads it the other way. (§2c)
- **A7 — `config_version` as a content hash** (`sha256:...`) rather than a hand-bumped string, because hand-bumped versions drift silently. (§3)
- **A8 — `client_order_id = <prefix><ledger-entry-id>`**, prefix from `ORDER_ID_PREFIX` in each box's `.env`, never hardcoded. Gives broker-level dedupe on retry. (§4)
- **A9 — `claimed_max_loss` / `claimed_max_gain`** kept but ADVISORY; governor computes independently and never trusts them. (§2d)
- **A10 — `order` / `fill` are `null`, never key-omitted**, and entries are append-only. (§5)
- **A11 — `screen_chain` does no file I/O**; the caller loads thresholds and passes the mapping in (GB-S-10 determinism; no component carries its own copy of a tunable). (§6a)

---

## B. Non-shape decisions (SETUP.md Phase 4.1)

| # | Decision | Options / notes |
|---|----------|-----------------|
| B1 | **Initial CURRENT LEADS** for every module row in the draft's lead table | SETUP 4.4 suggests: one side takes data layer + chain screener with golden fixtures, the other takes MCP wiring + NL intent path. Governor gets the deepest suite (GB-C) next. Leads rotate freely afterwards via HANDOFF blocks |
| B2 | **Demo platform** (Jhoosier picks) | Streamlit / Replit / Vercel. Needed for the SUBMISSION.md demo URL |
| B3 | **Competition account: who creates it, and when** | Fresh signup on the bare team address (the `+dev` plus-address is the dev account); ~Sep 1, "Monday if ready". $100k start; account ID goes into HANDOFF + SUBMISSION.md; keys via vault; governor-pipeline orders only, no manual orders ever |
| B4 | **`as_of` policy** | Same decision as **A5** — listed here too because SETUP 4.1 treats it as a scheduling decision, not only a shape one |

---

## C. Close-out actions once signed

1. Record both signatures in the draft's change log.
2. A human swaps `GB_INTERFACES.SIGNOFF-DRAFT.md` in over `GB_INTERFACES.md`
   (explicitly human-ordered; no AI pod performs the swap).
3. Declare initial leads in a HANDOFF block — that is what makes them current.
4. Note the demo platform and competition-account owner/timing in the same block.
5. Phase 4 DONE-WHEN: shapes signed, leads declared in HANDOFF, first two modules
   in progress on separate leads.

---

## D. Standing blockers to mention (not decisions)

- **Dev keys** are in the shared sheet as of 2026-08-31 ~03:55 UTC. The US-side
  a/b/c is still unverified: teakeycee fills `.env` from the sheet and runs
  `scripts/verify_gate.py`. Phase 3 DONE-WHEN needs both sides green.
- **`thresholds.PROPOSED.json` is uncalibrated** — `quote_max_age_seconds: 300`
  is a placeholder chosen to separate the fixture cases, not a trading judgement.
  Calibration is a later, separate pass.
