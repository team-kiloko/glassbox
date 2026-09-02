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
> **2026-09-02:** every `OPEN (sign-off):` item in this file has been resolved and
> is now marked **`DECIDED (2026-09-02)`** with its outcome. Positions and
> reasoning are in `docs/SIGNOFF_REVIEW_teakeycee.md`,
> `docs/SIGNOFF_REVIEW_jhoosier.md`, and `docs/F2_wire_check.md`. Both signatures
> are recorded in the change log.

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
| Data layer | **Jhoosier** |
| Chain screener | **teakeycee** |
| Strategist (NL intent → proposal) | **Jhoosier** |
| Governor + contract suites | **teakeycee** |
| Order builder / executor (Alpaca MCP) | **Jhoosier** |
| Provenance ledger | **teakeycee** |
| LLM backend layer | **Jhoosier** |
| NL intent UX | **Jhoosier** |
| Dashboard / report generation | **Jhoosier** |
| Telegram digest | **OPTIONAL (stretch) — lead unassigned** |
| Video + deck | **Jhoosier** |

**`DECIDED (2026-09-02):`** initial CURRENT LEADS as in the table above (agenda
B1). teakeycee: chain screener, governor + contract suites, provenance ledger,
and **strategist prompt review (adversarial)** — a review role on the Strategist
row, not the lead of it. Jhoosier: data layer, MCP executor, LLM backend +
strategist, NL intent UX, dashboard, video + deck. **Telegram digest is OPTIONAL
/ stretch** — not on the critical path, no lead assigned, built only if the
dashboard lands with time to spare. Leads become current when declared in a
HANDOFF block and rotate freely from there.

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
  "structure": "covered_call | cash_secured_put | vertical_spread",
  "qty": 1,
  "legs": [ { "symbol": "SPY260918C00640000",
              "action": "buy|sell", "option_type": "call|put",
              "strike": 0, "expiry": "YYYY-MM-DD", "ratio_qty": 1,
              "limit_price": 0.00 } ],
  "net_debit_credit": 0.00,
  "rationale": "plain-English why",
  "claimed_max_loss": 0, "claimed_max_gain": 0 }
```

#### 2a. `structure` is a CLOSED enum

`covered_call | cash_secured_put | vertical_spread`. No `...`, no open extension.
Governor scope is settled (CLAUDE.md): **defined-risk only** — covered calls,
cash-secured puts, defined-risk verticals; iron condors only as two verticals. A
`structure` value outside this enum is a governor rejection, not a passthrough.

**`DECIDED (2026-09-02):`** iron condor representation — **Option B, two composed
`vertical_spread` proposals**. `iron_condor` is **removed from the enum** and does
not appear anywhere in this seam.

**Normative note:** an iron condor is a **strategist-level composition of two
`vertical_spread` proposals** and **never crosses this seam as one structure**.
Each vertical is proposed, governed, ordered, and ledgered independently. This
matches the settled scope language literally, keeps max-loss math at the simple
per-vertical case with no special case in the governor, and removes the need for
the governor to verify wing symmetry. The accepted cost is two orders and two
ledger entries for what a human calls one position, and a window in which one
vertical fills and the other does not — acceptable on a paper account for this
event, and to be revisited for any future live system.

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

Each leg gains **`limit_price`**. The proposal gains **`net_debit_credit`**.

**Sign convention (normative, verified against the wire):** **positive = net debit
paid, negative = net credit received.** Confirmed 1:1 against Alpaca's
`LimitOrderRequest.limit_price` for `order_class: mleg` and the Level 3 guide
(`docs/F2_wire_check.md`, sources listed there). Seam and wire agree with no
translation layer for multi-leg orders.

**Units (normative):** **per-share, for ONE unit of the spread.** This is the
broker quoting convention: Alpaca's mleg `limit_price` is the net for one unit,
and the **100x contract multiplier and the order `qty` are applied downstream**.
Pinning the units matters as much as pinning the sign — a governor computing max
loss under the wrong units assumption is off by a factor of 100 with no field
that betrays it.

**`DECIDED (2026-09-02)`** — **C1, reconciliation rule (normative):**

```
net_debit_credit = sum over legs of  sign(action) * limit_price * ratio_qty
                   with buys positive and sells negative
```

**Per share, for one unit of the spread. The proposal `qty` is NOT a factor and
MUST NOT appear in this sum** — the wire limit is per unit of spread and is
independent of `qty`. If the reported `net_debit_credit` does not equal this sum,
the governor **rejects** the proposal (`net_reconciles`). This is an arithmetic
consistency check on the strategist's own numbers, not a market judgement, and it
runs before any risk math.

**Total dollar exposure = `net_debit_credit * 100 * qty`, computed by the governor
only.** That figure is never carried in the proposal; the multiplier is explicit
in governor math.

**`DECIDED (2026-09-02)`** — **C2, `ratio_qty` on legs, `qty` on the proposal:**
legs carry **`ratio_qty`** — positive integers in simplest form, **GCD across all
legs = 1**, mirroring the wire exactly. **`qty` moves to the proposal level** and
is the number of units of the structure. This removes the ambiguity of per-leg qty
versus order qty. **The GCD = 1 rule is enforced by the governor as part of the
`structure_valid` check.** Every structure in scope is 1:1 anyway.

Note why the net matters: **Alpaca multi-leg orders execute on a single net
limit.** The per-leg prices are the strategist's decomposition and are recorded
for audit; **the net is the executable figure**, and it is what the order carries
and what the governor's independent max-loss computation uses. For the single-leg
structures (`covered_call`, `cash_secured_put`) the wire mapping is different —
see the normative note in shape 4 (C3).

#### 2d. `claimed_max_loss` / `claimed_max_gain` — ADVISORY ONLY

The frozen file's `max_loss` / `max_gain` are renamed to **`claimed_max_loss`**
and **`claimed_max_gain`** and are marked **ADVISORY**.

The governor **computes max loss independently** from strikes, `ratio_qty`, `qty`,
and net price, and **never trusts these fields** (CLAUDE.md: "The governor
computes max loss independently; it never trusts a strategist-supplied figure").
The renaming is deliberate: a field called `max_loss` invites a reader — human or
model — to treat it as the risk figure. `claimed_` makes the provenance unmissable
at every call site.

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

**`DECIDED (2026-09-02):`** reservation producer — **option (b), the governor
maintains `reserved_cash` / `reserved_shares` from the ledger.** The data layer
**reports raw broker state only** and stays a dumb, honest reporter: its job is
honesty, not judgement. The component that owns risk owns "this collateral is
already spoken for", and the ledger literally drives the coverage story.

**Data layer output — raw broker state, no reservations:**

```json
{ "as_of": "iso-utc",
  "cash": 0.00,
  "buying_power": 0.00,
  "positions": { "SPY": { "shares": 0 } } }
```

**Governor's composed view — raw state plus ledger-derived reservations:**

```json
{ "as_of": "iso-utc",
  "cash": 0.00,
  "buying_power": 0.00,
  "reserved_cash": 0.00,
  "positions": { "SPY": { "shares": 0, "reserved_shares": 0 } } }
```

The field names are unchanged from the pre-sign-off draft; only the **producer**
changed. `reserved_cash` and `reserved_shares` are **derived by the governor from
the provenance ledger** (shape 5) and never requested from or supplied by the data
layer.

PLACEHOLDER field names and values. Minimal by design — only what the
defined-risk checks need:

- **`positions[<underlying>].shares`** — share count per underlying, for
  covered-call coverage (100 shares per contract, per the contract `multiplier`).
  Raw broker state, from the data layer.
- **`positions[<underlying>].reserved_shares`** — shares already committed to
  other open short calls, so two covered calls cannot claim the same 100 shares.
  **Governor-derived from the ledger.**
- **`cash`** — raw broker state, from the data layer.
- **`reserved_cash`** — collateral already committed to other cash-secured puts,
  so two puts cannot claim the same collateral. **Governor-derived from the
  ledger.**
- **`buying_power`** — for defined-risk verticals. Raw broker state.
- **`as_of`** — the timestamp this account read is true as of, so a stale account
  read is detectable rather than silently trusted (same discipline as the
  screener's `as_of`; see shape 6b).

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

#### 3a. `checks[]` rule vocabulary — HYBRID, pinned core

**`DECIDED (2026-09-02):`** hybrid. The **core `checks[]` vocabulary is pinned in
this seam**:

`structure_valid | net_reconciles | max_loss_cap | coverage | cash_floor | churn_guard | market_open`

These names are stable seam vocabulary: the dashboard and the write-up name them,
and the GB-C contract suite asserts against them, so a rename mid-crunch breaks
the demo. Renaming or removing a core check **requires a seam change**, i.e. both
humans.

**The governor lead MAY add non-seam checks under an `x_` prefix** (e.g.
`x_liquidity_floor`) **without a seam change.** The dashboard renders the core
checks by name and any `x_` check generically.

Notes on individual core checks:

- **`structure_valid`** — the declared `structure` matches the actual leg
  composition, and leg `ratio_qty` values are positive integers with GCD 1 (2c/C2).
- **`net_reconciles`** — the per-share reconciliation rule in 2c/C1.
- **`coverage`** — structure-vs-legs-vs-account-state (2e), against the governor's
  composed account view (2b).
- **`market_open`** — see 6c. Required to pass before order **submission**;
  screening and proposing do not require it.

---

### 4. Order  (Executor via Alpaca MCP → Ledger)

```json
{ "client_order_id": "<prefix><ledger-entry-id>",
  "order_id": "...",
  "status": "filled | rejected | ...",
  "underlying": "SPY",
  "qty": 1,
  "legs": [ { "symbol": "SPY260918C00640000",
              "side": "buy|sell", "ratio_qty": 1,
              "position_intent": "buy_to_open|sell_to_open" } ],
  "net_limit_price": 0.00,
  "submitted_at": "iso-utc",
  "fill": { } }
```

The order shape mirrors the wire: the **parent** carries `qty`, `type: limit`,
`limit_price`, `time_in_force: day`, and (for 2–4 leg structures)
`order_class: mleg`; **legs** carry `symbol`, `side`, `ratio_qty`, and
`position_intent`. The proposal's per-leg `action` maps to the wire's `side`.

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

#### 4a. Single-leg structures are NOT `mleg` — normative

**`DECIDED (2026-09-02)`** — **C3.** `covered_call` and `cash_secured_put` are
**single-leg option orders, not `mleg`** — `mleg` requires 2 or more legs. Only
`vertical_spread` goes out as `mleg`.

On a **single-leg** order the wire `limit_price` is **always positive** and the
direction comes from **`side`**. The seam's signed `net_debit_credit` therefore
maps to the wire as:

```
limit_price = abs(net_debit_credit)
side        = from the leg's action  (a CSP's negative credit -> side: sell)
```

**Never submit a negative limit price on a single-leg order.** This is the one
place where the seam does not map 1:1 to the wire, and the mapping lives in **the
executor's structure-tagged constructors** — one line, in the same place that
already enforces the covering-asset argument (2e). It is recorded here so nobody
re-derives it, or forgets it, somewhere else.

#### 4b. `position_intent` — normative

**`DECIDED (2026-09-02)`** — **C4.** Each order leg carries **`position_intent`**.
For this event the pipeline is **opening-only**:

```
action buy   ->  position_intent: buy_to_open
action sell  ->  position_intent: sell_to_open
```

`buy_to_close` / `sell_to_close` are **reserved** in the vocabulary for closing
trades and are not emitted by this pipeline. If early exits are ever added, they
use the `_to_close` intents and this note is what they amend.

---

### 5. Ledger entry  (the audit record; consumed by the dashboard)

```json
{ "id": "...",
  "root_id": null,
  "ts": "iso-utc",
  "as_of": "iso-utc",
  "mode": "approve | autopilot",
  "status": "governor_rejected | submitted | broker_rejected | filled | partial_fill | expired | canceled",
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

#### 5a. In-flight status — append-only chains, root id

**`DECIDED (2026-09-02):`** **option (c) — each transition is a new appended entry
referencing the root entry's id.** This is **forced, not preferred**
(`docs/SIGNOFF_REVIEW_teakeycee.md` finding F1, accepted by Jhoosier): shape 4
requires the ledger entry to exist **before** submission so `client_order_id` can
embed its `id`; the fill arrives **after** the entry exists; and this file's
append-only rule forbids writing it back. Options (a) and (b) each contradict one
of those three, so (c) is the only consistent choice.

The chain:

1. **Root entry — the decision entry.** Written **pre-submission**, with
   `order: null` and `fill: null`, carrying `snapshot` / `proposal` / `verdict` and
   the full provenance block. Its `root_id` is **`null`** — a root entry is its own
   root. Its `id` is what `client_order_id` embeds.
2. **Follow-up entries** are appended for **submission, fill, partial fill, or
   broker rejection**, each with **`root_id` set to the root entry's `id`**. A
   follow-up carries the new `status` and the `order` / `fill` payload that
   transition produced.

**The dashboard folds chains by root id** — one position, one row, its history
expandable underneath.

#### Entry-level `status` vocabulary

`governor_rejected | submitted | broker_rejected | filled | partial_fill | expired | canceled`

- **`submitted`** is added for the in-flight window between submission and a
  terminal state (agenda A4).
- **`partial_fill` is NON-TERMINAL.** Alpaca's `partially_filled` is not an end
  state, and a terminal-only vocabulary misfiles it. A `partial_fill` follow-up may
  be succeeded by further follow-ups on the same root — a later `filled`,
  `expired`, or `canceled`.
- `governor_rejected` and `broker_rejected` stay deliberately separate — "we
  refused" and "they refused" are different facts about the system, and the
  dashboard should never blur them.

Still marked **PROPOSED** as to completeness: this is a working vocabulary, and
adding a value is a seam change.

#### Provenance fields

- **`id`** — the entry id. The scheme `client_order_id` builds on (shape 4).
- **`root_id`** — `null` on a root (decision) entry; the root entry's `id` on every
  follow-up. The fold key for the dashboard.
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
that references the id of the entry it corrects.** Order progress is handled the
same way, by appended follow-ups chained on `root_id` (5a). There is no in-place
status update anywhere in this system.

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

`null_greeks | missing_bid | missing_ask | stale_quote | no_snapshot`

**`DECIDED (2026-09-02):`** **`missing_ask` is added** (agenda F3, both pods
accept). `tests/fixtures/expected_verdicts.json` named only `missing_bid`, but
**`thresholds.PROPOSED.json` requires a TWO-SIDED quote**: a contract with a bid
and no ask must be rejected under that rule and previously had no code to be
rejected *with*, which would either violate GB-S-06's machine-readable-reason
guarantee or force a mislabel. It matters beyond symmetry: verticals **buy** a
leg, so a missing ask is un-executable on the long side.

> **Not yet in the fixtures.** The counter-fixture (greeks complete, fresh, bid
> present, ask absent) and its test land in teakeycee's screener session, as the
> screener lead — **not in the sign-off commit**. Until then `expected_verdicts.json`
> names four codes and the seam names five; the seam is the authority.

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

#### 6c. Caller policy for choosing `as_of` — DECIDED

The screener's `as_of` semantics (6b) are settled. **What the caller passes** was
not, and teakeycee flagged it as a both-humans decision (HANDOFF 2026-08-30 22:07
UTC): any quote is hours old outside market hours, so a naive freshness rule
rejects everything on a weekend.

**`DECIDED (2026-09-02):`** **option (a) as proposed, plus a `market_open` governor
check.**

- Market **open** → `as_of = now`.
- Market **closed** → `as_of = the last close`, obtained from Alpaca's
  **`/v2/clock`** and **`/v2/calendar`** endpoints. **No hand-rolled market
  calendar** — holidays, half-days, and early closes are exactly the cases a
  hand-rolled calendar gets wrong, and getting one wrong means either screening
  against dead data or refusing to screen on a live day. The data layer exposes
  `clock()` and `calendar()` pass-throughs so no component hand-rolls one.
- **Screening and proposing run at any time** (demos, dry runs, off-hours
  preparation).
- **Order submission requires `market_open` to pass in the governor's `checks`**
  (shape 3a). The freshness threshold does little work off-hours, so the safety
  lives in the governor, where it belongs — and the scored account can still trade
  at the open.

This affects **run scheduling** and the **scored P&L window**, which is why it was
a decision and not a default.

---

## Change log

- 2026-08-28 — file created; all shapes DRAFT, pending both humans' sign-off.
- 2026-08-31 — **sign-off draft prepared** (Jhoosier pod, at teakeycee's
  Attack-next request). `GB_INTERFACES.md` itself untouched and still frozen;
  this is a proposed replacement awaiting review.

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

- 2026-09-02 — **SIGN-OFF. Every open item resolved.** Sources:
  `docs/SIGNOFF_REVIEW_teakeycee.md`, `docs/SIGNOFF_REVIEW_jhoosier.md`,
  `docs/F2_wire_check.md`, `docs/signoff_agenda.md`.

  Decided this entry:

  - **A1 — iron condor: Option B.** `iron_condor` removed from the `structure`
    enum (§2, §2a); a condor is a strategist-level composition of two
    `vertical_spread` proposals and never crosses the seam as one structure.
  - **A2 — reservations: (b) governor-from-ledger.** §2b split into a data-layer
    output (raw broker state, no reservations) and the governor's composed view;
    `reserved_cash` / `reserved_shares` are governor-derived from the ledger.
  - **A3 — `checks[]`: hybrid.** Core vocabulary pinned in §3a:
    `structure_valid, net_reconciles, max_loss_cap, coverage, cash_floor,
    churn_guard, market_open`. Governor lead may add non-seam checks under an
    `x_` prefix without a seam change.
  - **A4 — ledger status in flight: (c),** forced by the id-first + append-only
    architecture (teakeycee F1). §5a: root decision entry written pre-submission
    with `order`/`fill` null and `root_id: null`; submission, fill, partial fill,
    and broker rejection are appended follow-ups carrying `root_id`. `submitted`
    added to the status vocabulary; `partial_fill` recorded as NON-terminal.
    Dashboard folds chains by root id.
  - **A5 / B4 — `as_of`: (a) plus `market_open`.** §6c: caller `as_of = now` when
    open, last close via `/v2/clock` + `/v2/calendar` when closed, no hand-rolled
    calendars; screening and proposing run any time, order submission requires
    `market_open` to pass in the governor's checks.
  - **A6 / F2 — sign convention verified, units pinned, four wire amendments
    applied** (`docs/F2_wire_check.md`):
    - **C1** — reconciliation is per-share for one unit of spread, the `qty`
      factor is dropped:
      `net_debit_credit = sum(sign(action) * limit_price * ratio_qty)`;
      total dollars = `net * 100 * qty`, computed by the governor only (§2c).
    - **C2** — legs carry `ratio_qty` (positive integers, GCD 1 enforced as a
      `structure_valid` check); `qty` moves to the proposal level (§2, §2c).
    - **C3** — normative note that `covered_call` and `cash_secured_put` are
      single-leg orders, not `mleg`: wire `limit_price = abs(net)` with direction
      from `side`; mapping lives in the executor's structure-tagged constructors;
      never submit a negative limit on a single-leg order (§4a).
    - **C4** — `position_intent` added to the order shape; opening-only mapping
      for this event (`buy -> buy_to_open`, `sell -> sell_to_open`); `_to_close`
      reserved (§4b).
  - **F3 — `missing_ask` added** to the shape 6 screener reason-code vocabulary;
    the two-sided-quote threshold requires it. Counter-fixture and test land in
    teakeycee's screener session, not in this commit.
  - **B1 — CURRENT LEAD table filled.** teakeycee: chain screener, governor +
    contract suites, provenance ledger, strategist prompt review. Jhoosier: data
    layer, MCP executor, LLM backend + strategist, NL intent UX, dashboard,
    video + deck. Telegram digest: OPTIONAL (stretch), lead unassigned.

  Confirmed in passing, unchanged: A7 (`config_version` content hash), A8
  (`client_order_id` scheme), A9 (`claimed_*` advisory), A10 (nullable
  `order`/`fill`, append-only — as modified by A4(c)), A11 (no file I/O in
  `screen_chain`).

  **Signatures — BOTH RECORDED.**
  - **teakeycee — signed 2026-09-02** (this commit).
  - **Jhoosier — accepted 2026-09-02**, per `docs/SIGNOFF_REVIEW_jhoosier.md`
    ("Ready to sign") and his HANDOFF block of 2026-09-02 06:10 UTC.
