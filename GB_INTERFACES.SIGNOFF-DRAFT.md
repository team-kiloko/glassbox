# GB_INTERFACES.SIGNOFF-DRAFT.md — the seam (sign-off draft)

> **STATUS: DRAFT FOR SIGN-OFF. NOT YET IN FORCE.**
> `GB_INTERFACES.md` is FROZEN pre-sign-off and remains the file of record until
> both humans sign. This document is a complete proposed replacement for it,
> prepared by the Jhoosier pod at teakeycee's Attack-next request
> (HANDOFF 2026-08-30 22:07 UTC: "come to sign-off ready on: seam shapes +
> my proposed screen_chain seam").
>
> **How this file is used:** both humans review it at the Phase 4 touchpoint
> (SETUP.md Phase 4.1). Objections are marked inline. Only after BOTH sign does
> a human swap it in over `GB_INTERFACES.md`. That swap is a separate, explicitly
> human-ordered step. No AI pod performs it.
>
> Items marked **`OPEN (sign-off):`** are decisions that belong to the humans at
> the touchpoint. They are presented with options and trade-offs; they are NOT
> pre-decided here. Every open item is also listed in `docs/signoff_agenda.md`.

---

## What this file is

> The ONE place every data shape that crosses between the two pods is defined.
> **RULE:** a field changes HERE FIRST, by human agreement, before any code depends on it.
> Each pod builds in its own isolated context; this file is the only thing they share.

Parties: **teakeycee** (US side) and **Jhoosier** (Japan side). The earlier
"Tiki / TKC" labels are stale and are retired by this draft.

Field names and values marked **PLACEHOLDER** are shapes to agree on, not
calibrated judgements. Thresholds and tunables live in config, never in code
(CLAUDE.md); anything not yet calibrated is marked **PROPOSED**.

## Current lead per module

Leads are not fixed ownership. Exactly one human is the current lead of a given
module at any moment, and only the lead merges changes to it; leads rotate by
declaration in a HANDOFF block, per `HANDOFF_PROTOCOL.md` ("Current lead per
module — the collision rule"). Anyone may contribute anywhere, and cross-pod
adversarial fixtures are always welcome against any module; fixes stay with the
lead.

| Module | Current lead |
|--------|--------------|
| Data layer | `set at sign-off` |
| Chain screener | `set at sign-off` |
| Strategist (NL intent → proposal) | `set at sign-off` |
| Governor + contract suites | `set at sign-off` |
| Order builder / executor (Alpaca MCP) | `set at sign-off` |
| Provenance ledger | `set at sign-off` |
| LLM backend layer | `set at sign-off` |
| NL intent UX | `set at sign-off` |
| Dashboard / report generation | `set at sign-off` |
| Telegram digest | `set at sign-off` |
| Video + deck | `set at sign-off` |

**`OPEN (sign-off):`** initial CURRENT LEADS for every row above. SETUP.md
Phase 4.4 suggests an opening split — one side takes data layer + chain screener
with golden fixtures, the other takes MCP wiring + NL intent path — but the
assignment is the humans' call.

---

## The pipeline, and the shapes that cross the seam

Flow: **chain screen → NL intent → strategy proposal → governor verdict → order + fill → ledger entry.**

The chain screener feeds the strategist the tradable universe; its seam (shape 6)
was previously undefined here and lived only in `tests/conftest.py`. This draft
lifts it in.

---

### 1. NL intent  (UX pod → Strategist)

```json
{ "intent_text": "NVDA flat for two weeks",
  "ticker": "NVDA", "horizon_days": 14,
  "view": "flat | up | down | volatile" }
```

Unchanged from the frozen file. PLACEHOLDER values.

---

### 2. Strategy proposal  (Strategist → Governor)

```json
{ "underlying": "SPY",
  "structure": "covered_call | cash_secured_put | vertical_spread | iron_condor",
  "legs": [ { "symbol": "SPY260918C00640000",
              "action": "buy|sell", "option_type": "call|put",
              "strike": 0, "expiry": "YYYY-MM-DD", "qty": 1,
              "limit_price": 0.00 } ],
  "net_debit_credit": 0.00,
  "rationale": "plain-English why",
  "claimed_max_loss": 0, "claimed_max_gain": 0 }
```

#### 2a. `structure` is a CLOSED enum

`covered_call | cash_secured_put | vertical_spread | iron_condor`. No `...`, no
open extension. Governor scope is settled (CLAUDE.md): **defined-risk only** —
covered calls, cash-secured puts, defined-risk verticals; iron condors only as
two verticals. A `structure` value outside this enum is a governor rejection, not
a passthrough.

**`OPEN (sign-off):`** iron condor representation.

- **Option A — one 4-leg proposal** with `structure: "iron_condor"`. One order,
  one ledger entry, one net credit. The governor must then know that the max loss
  of a condor is *one wing*, not the sum of both, and must verify wing symmetry
  itself.
- **Option B — two `vertical_spread` proposals**, composed. Matches the settled
  scope language ("iron condors only as two verticals") literally; max-loss math
  stays the simple per-vertical case with no special case in the governor; costs
  two orders and two ledger entries for what a human calls one position, and
  leaves a window where one vertical fills and the other does not.

This decision affects **max-loss math** (risk is one wing, not two), **order
count** at the broker, and **ledger shape** (one entry vs. two linked entries).
`structure: "iron_condor"` stays in the enum only under Option A; under Option B
it is removed and the composition is a strategist-level concept that never
crosses this seam.

#### 2b. Legs carry `symbol`; the proposal carries `underlying`

Each leg gains **`symbol`** — the OCC contract symbol (e.g.
`SPY260918C00640000`), exactly as returned by `/v2/options/contracts` and keyed
in `/v1beta1/options/snapshots`. The proposal gains **`underlying`** — the plain
ticker.

Rationale, and this is load-bearing: in the frozen file legs carry no symbol at
all, only `option_type`/`strike`/`expiry`. **The governor's output cannot become
an order without it.** Alpaca orders are placed against contract symbols;
reconstructing an OCC symbol from type/strike/expiry inside the executor would be
a second, silent source of truth for which contract is being traded. The symbol
comes from the screener, rides the proposal, and reaches the order unchanged.

This also matches the screener seam (shape 6), whose `accepted` entries are
`{symbol, option_type, strike, expiry}` — a screened contract drops straight into
`legs[]`.

#### 2c. Prices: per-leg `limit_price` and proposal `net_debit_credit`

Each leg gains **`limit_price`**. The proposal gains **`net_debit_credit`**
(PLACEHOLDER sign convention: positive = net debit paid, negative = net credit
received — confirm at sign-off if either pod's code reads it the other way).

**Reconciliation rule (normative):** `net_debit_credit` MUST equal the signed sum
of each leg's `limit_price` × `qty`, with buys positive and sells negative. If it
does not, the governor **rejects** the proposal. This is an arithmetic
consistency check on the strategist's own numbers, not a market judgement, and it
runs before any risk math.

Note why the net matters: **Alpaca multi-leg orders execute on a single net
limit.** The per-leg prices are the strategist's decomposition and are recorded
for audit; **the net is the executable figure**, and it is what the order carries
and what the governor's independent max-loss computation uses.

#### 2d. `claimed_max_loss` / `claimed_max_gain` — ADVISORY ONLY

The frozen file's `max_loss` / `max_gain` are renamed to **`claimed_max_loss`**
and **`claimed_max_gain`** and are marked **ADVISORY**.

The governor **computes max loss independently** from strikes, qty, and net
price, and **never trusts these fields** (CLAUDE.md: "The governor computes max
loss independently; it never trusts a strategist-supplied figure"). The renaming
is deliberate: a field called `max_loss` invites a reader — human or model — to
treat it as the risk figure. `claimed_` makes the provenance unmissable at every
call site.

The fields are **kept, not deleted**. They are the strategist's stated belief,
which is worth auditing: the GB-C governor suite will include a fixture where the
claim is false and the governor catches the discrepancy (SETUP.md Phase 4.4). A
divergence between claimed and computed is itself a signal worth surfacing in the
verdict and the ledger.

#### 2e. Naked-short prevention is NOT a property of this schema

Stated explicitly because it is the single most inviting wrong assumption in this
document.

The frozen file says "No naked short option is expressible." That is the correct
**invariant**, but it is not enforced by this shape and cannot be. A covered call
is a lone short call leg. A cash-secured put is a lone short put leg. Written as
`legs[]`, each is indistinguishable from a naked short. **What makes them
defined-risk is account state** — the 100 shares per contract behind the call,
the reserved cash behind the put — which does not appear in the proposal at all.

The invariant is enforced in two places, neither of them here:

1. **The order builder**, via structure-tagged constructors that require the
   covering asset as an argument. There is no code path that builds a lone short
   option leg without one; the naked case is unrepresentable in the builder's
   API, not merely rejected by it.
2. **The governor's structure-vs-legs-vs-account-state check**, which confirms
   that the declared `structure` matches the actual leg composition AND that the
   account state (shape 2b) actually covers it.

A reviewer reading only `legs[]` and concluding the system is safe has read the
wrong file. That is why this note is normative text in the seam.

---

### 2b. Account state  (Data layer → Governor)  — NEW SHAPE

Input to the governor. Without it, the defined-risk checks in 2e cannot run: the
governor cannot confirm that a short call is covered or a short put is secured.

```json
{ "as_of": "iso-utc",
  "cash": 0.00,
  "buying_power": 0.00,
  "reserved_cash": 0.00,
  "positions": { "SPY": { "shares": 0, "reserved_shares": 0 } } }
```

PLACEHOLDER field names and values. Minimal by design — only what the
defined-risk checks need:

- **`positions[<underlying>].shares`** — share count per underlying, for
  covered-call coverage (100 shares per contract, per the contract `multiplier`).
- **`positions[<underlying>].reserved_shares`** — shares already committed to
  other open short calls, so two covered calls cannot claim the same 100 shares.
- **`cash`** and **`reserved_cash`** — for cash-secured-put coverage, so two puts
  cannot claim the same collateral.
- **`buying_power`** — for defined-risk verticals.
- **`as_of`** — the timestamp this account read is true as of, so a stale account
  read is detectable rather than silently trusted (same discipline as the
  screener's `as_of`; see shape 6b).

**`OPEN (sign-off):`** whether `reserved_cash` / `reserved_shares` are computed by
the data layer from open orders and positions, or maintained by the governor from
the ledger. The governor-from-ledger route keeps reservation logic in the
component that owns risk; the data-layer route keeps it closer to the broker's own
view. Either way the field names stay; only the producer changes.

---

### 3. Governor verdict  (Governor → Executor / Ledger)

```json
{ "approved": true,
  "mode": "approve | autopilot",
  "config_version": "sha256:...",
  "checks": [ { "rule": "max_loss_cap", "passed": true,
                "detail": "computed_max_loss=250.00 vs cap=500.00" } ],
  "reason": "plain-English verdict" }
```

The governor is the ONLY component that may emit an order.

- **`mode`** — `approve` (a human confirms before submission) or `autopilot` (the
  governor's approval is sufficient). It appears in the verdict-to-order path per
  SETUP.md Phase 4.2, and it is recorded on the ledger entry so an audit can tell
  whether a human was in the loop for any given trade.

- **`config_version`** — identifies exactly which thresholds produced this
  verdict. **Recommended: a content hash of the config file** (e.g.
  `sha256:<hex>`), not a hand-bumped version string. Hand-bumped versions drift:
  the value someone forgot to bump is indistinguishable from the value they
  correctly left alone, and the drift is silent and unrecoverable after the fact.
  A content hash cannot drift from its content. It is also cheap — the config is
  a small file read once per run.

- **The governor's independently computed max loss appears in `checks` detail** —
  not only the pass/fail. The number the governor actually computed must be
  visible in the record, alongside the cap it was compared against and, where the
  proposal supplied one, the `claimed_max_loss` it diverged from. A verdict that
  says only `"passed": true` is not an audit record.

- **`prompt_version` does NOT belong here.** The governor is deterministic and
  has no prompt. Putting a prompt version on its verdict would imply an LLM in
  the risk path, which is exactly the property GlassBox is claiming it does not
  have. `prompt_version` attaches to the **strategy proposal** (which is
  LLM-produced) and is carried on the **ledger entry** (shape 5).

**`OPEN (sign-off):`** whether the `checks[]` rule vocabulary is pinned in this
file (like the screener's reason codes) or left to the governor lead. Pinning it
makes the dashboard and the GB-C suite stable against rule renames; leaving it
open lets the governor lead add checks without a seam change.

---

### 4. Order  (Executor via Alpaca MCP → Ledger)

```json
{ "client_order_id": "<prefix><ledger-entry-id>",
  "order_id": "...",
  "status": "filled | rejected | ...",
  "underlying": "SPY",
  "legs": [ { "symbol": "SPY260918C00640000", "action": "buy|sell", "qty": 1 } ],
  "net_limit_price": 0.00,
  "submitted_at": "iso-utc",
  "fill": { } }
```

#### `client_order_id` — normative

Every order built anywhere in this codebase carries a `client_order_id` whose
prefix comes from **`ORDER_ID_PREFIX` in that box's `.env`** (CLAUDE.md). The
prefix is **never hardcoded in tracked code** — not in the order builder, not in
a default argument, not in a test that later becomes the reference
implementation. Code reads the env var; if it is unset, the builder fails rather
than guessing.

`tkc-` (teakeycee's box) and `jho-` (Jhoosier's box) are the current values and
may appear **as examples only, clearly marked as such** — as they are here. They
are configuration, not constants.

#### Id scheme

`client_order_id = <prefix> + <ledger-entry-id>`, where `<ledger-entry-id>` is the
ledger entry's `id` (shape 5). The ledger entry is written before submission, so
its id exists first and the order references it, not the other way round.

This gives **idempotency at the broker**: a retried submission — after a timeout,
a crash mid-submit, or an ambiguous network failure — carries the same
`client_order_id`, and Alpaca rejects the duplicate rather than opening a second
position. Without it, the safe answer to "did my order go through?" is a manual
check, which is not a property this system can afford on a scored account.

---

### 5. Ledger entry  (the audit record; consumed by the dashboard)

```json
{ "id": "...",
  "ts": "iso-utc",
  "as_of": "iso-utc",
  "mode": "approve | autopilot",
  "status": "governor_rejected | broker_rejected | filled | partial_fill | expired | canceled",
  "config_version": "sha256:...",
  "prompt_version": "...",
  "code_version": "<git-sha>",
  "approved_by": null,
  "approved_at": null,
  "snapshot": { },
  "proposal": { },
  "verdict": { },
  "order": null,
  "fill": null }
```

#### `order` and `fill` are explicitly NULLABLE

When the governor rejects, there is no order and no fill. Those keys are present
with value **`null`** — **never omitted**. An omitted key is indistinguishable
from a truncated write, a serialization bug, or a corrupted record; a `null` is a
positive statement that the pipeline reached this point and stopped here. In an
audit record that distinction is the whole point.

#### Entry-level `status` vocabulary — PROPOSED (draft)

`governor_rejected | broker_rejected | filled | partial_fill | expired | canceled`

Marked PROPOSED: this is a first draft of the vocabulary, not a calibrated one.
It deliberately separates `governor_rejected` from `broker_rejected` — "we
refused" and "they refused" are different facts about the system, and the
dashboard should never blur them.

**`OPEN (sign-off):`** whether the vocabulary needs `submitted` / `pending` for
the window between submission and a terminal state, and whether an entry's
`status` may be updated in place as an order progresses — which collides with the
append-only rule below. Options: (a) status is terminal-only and an in-flight
order has no entry status yet; (b) status may advance through non-terminal values
in place; (c) each transition is a new appended entry referencing the prior id.

#### Provenance fields

- **`id`** — the entry id. The scheme `client_order_id` builds on (shape 4).
- **`as_of`** — the **data timestamp** the run screened and priced against.
  Distinct from `ts` (when the entry was written). Two runs at different wall
  clocks against the same `as_of` should produce the same verdicts; that is what
  makes the pipeline auditable, and it is what GB-S-10 asserts for the screener.
- **`config_version`** — content hash of the config (shape 3).
- **`prompt_version`** — the strategist prompt that produced the proposal. This
  is where it lives (not on the verdict; see shape 3).
- **`code_version`** — git SHA of the code that ran.
- **`mode`** — `approve` or `autopilot`, as on the verdict.
- **`approved_by`** / **`approved_at`** — the human who confirmed, and when.
  **Both `null` in autopilot mode**, which is a recorded fact, not a gap.

Together these answer, for any entry, months later: what data, what config, what
prompt, what code, and who said yes.

#### Append-only — normative

**Ledger entries are never mutated and never deleted; a correction is a new entry
that references the id of the entry it corrects.** (See the open item under
`status` above, which is the one place this rule is under discussion.)

---

### 6. Chain screener seam  (Data layer → Strategist)  — NEW SHAPE

Lifted verbatim from `tests/conftest.py`, where it was proposed rather than
written into the frozen seam. It has been exercised by the GB-S contract suite
since commit 77714be (4 fixture-integrity tests passing, 12 behaviour tests
strict-xfail, auto-arming when a module exposing `screen_chain()` appears).

```
screen_chain(contracts, snapshots, as_of, thresholds) -> result

  contracts  : the parsed /v2/options/contracts body (dict with
               "option_contracts": [...])
  snapshots  : the parsed /v1beta1/options/snapshots body (dict with
               "snapshots": {symbol: {...}})
  as_of      : timezone-aware datetime the freshness check is measured against
  thresholds : mapping of tunables (see tests/fixtures/thresholds.PROPOSED.json)

  result     : mapping or object exposing
                 .accepted -> [{symbol, option_type, strike, expiry}, ...]
                 .rejected -> [{symbol, reasons: [code, ...]}, ...]
               Every input contract appears in exactly one of the two lists.
```

`accepted` entries are shaped to drop straight into shape 2 `legs[]`
(`symbol` / `option_type` / `strike` / `expiry`).

#### Reason-code vocabulary — PROPOSED

From `tests/fixtures/expected_verdicts.json`:

`null_greeks | missing_bid | stale_quote | no_snapshot`

A contract may carry more than one reason; **order is not significant**. The
screener **fails closed**: a contract it cannot fully evaluate is rejected with a
reason, never accepted on a guess and never silently skipped. Null greeks are
`null`, not zero and not absent (CLAUDE.md: "The screener must fail closed on null
greeks, never guess"). A contract absent from `snapshots` is a reject
(`no_snapshot`), not a skip and not a retry.

#### 6a. The CALLER loads the thresholds config — normative

`screen_chain` receives `thresholds` as a **mapping passed in by its caller**. It
performs **no file I/O**: it does not open a config file, does not know a config
path, and does not fall back to a built-in default when a key is missing.

Two reasons, both binding:

1. **Determinism.** GB-S-10 asserts identical inputs give identical verdicts, with
   no clock and no randomness. A function that reads a file is a function whose
   output depends on the filesystem at call time. Purity here is a contract-suite
   requirement, not a style preference.
2. **One copy of each tunable.** Per CLAUDE.md, thresholds live in config, never
   hardcoded — and **no component carries its own copy of a tunable**. The config
   is read once, at the edge, and passed down. The contract suite holds itself to
   the same rule: it loads `thresholds.PROPOSED.json` and passes it in rather than
   inlining values.

#### 6b. Freshness is measured against `as_of`, never wall clock — normative

Quote age is `as_of − quote.t`. The screener never calls the clock.

This is fixtures README trap #2, and it is subtle because **a stale quote looks
perfectly healthy field-by-field**: fixture `SPY260918C00655000` has complete
greeks and a tight two-sided quote, and only its timestamp betrays it. A screener
that checks freshness against wall-clock-at-read-time produces different verdicts
for the same data depending on when it runs, which breaks both the audit trail and
GB-S-10.

`thresholds.quote_max_age_seconds` is currently `300` and is **PROPOSED,
uncalibrated** — chosen so the stale fixture sits unambiguously outside it and
every fresh case unambiguously inside. It is not a trading judgement.

#### 6c. Caller policy for choosing `as_of` — PROPOSED, `OPEN (sign-off):`

The screener's `as_of` semantics (6b) are settled. **What the caller passes** is
not, and teakeycee flagged it as a both-humans decision (HANDOFF 2026-08-30 22:07
UTC): any quote is hours old outside market hours, so a naive freshness rule
rejects everything on a weekend.

Proposed policy, **PROPOSED and OPEN**:

- Market **open** → `as_of = now`.
- Market **closed** → `as_of = the last close`, obtained from Alpaca's
  **`/v2/clock`** and **`/v2/calendar`** endpoints. **No hand-rolled market
  calendar** — holidays, half-days, and early closes are exactly the cases a
  hand-rolled calendar gets wrong, and getting one wrong means either screening
  against dead data or refusing to screen on a live day.

Alternatives to weigh at the touchpoint: **market-hours-only screening** (never
run when closed; simplest, but concedes any off-hours preparation), versus
**closed-market screening against the last close** (allows off-hours runs, but
every quote is by definition maximally stale relative to `now`, and the freshness
threshold is then doing no work).

This affects **run scheduling** and the **scored P&L window**, which is why it is
a decision and not a default.

---

## Change log

- 2026-08-28 — file created; all shapes DRAFT, pending both humans' sign-off.
- 2026-08-31 — **sign-off draft prepared** (Jhoosier pod, at teakeycee's
  Attack-next request). `GB_INTERFACES.md` itself untouched and still frozen;
  this is a proposed replacement awaiting review.
  **Both signatures pending: teakeycee `___`, Jhoosier `___`.**

  Shapes touched: header and parties relabelled to teakeycee / Jhoosier;
  ownership table replaced with a CURRENT LEAD table (leads `set at sign-off`);
  **shape 2 strategy proposal** (closed `structure` enum, leg `symbol`, proposal
  `underlying`, leg `limit_price`, `net_debit_credit` + reconciliation rule,
  `max_loss`/`max_gain` renamed to `claimed_*` and marked ADVISORY, naked-short
  enforcement note); **shape 2b account state** (NEW); **shape 3 governor
  verdict** (`mode`, `config_version` as content hash, computed max loss in
  `checks` detail, `prompt_version` excluded); **shape 4 order**
  (`client_order_id`, prefix-from-env rule, id scheme for broker idempotency);
  **shape 5 ledger entry** (`order`/`fill` nullable, `status` vocabulary,
  provenance fields, append-only rule); **shape 6 chain screener seam** (NEW,
  lifted from `tests/conftest.py`).

  Open items carried to the touchpoint: iron condor representation; reservation
  producer for account state; `checks[]` rule vocabulary; ledger `status`
  in-flight handling; caller `as_of` policy; initial CURRENT LEADS. Full list,
  with the non-shape Phase 4.1 decisions, in `docs/signoff_agenda.md`.
