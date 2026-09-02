# HANDOFF — GlassBox

> The baton. Prepend a new dated block at the TOP of this file each work session.
> READ THIS FIRST, before doing anything. Write your closing block LAST, before you stop.
> Follow-the-sun: Tokyo's day ends as Minneapolis's begins — keep it current so the
> other pod can start cold, with no verbal context.

## How to use
Copy the block below, fill it in, and put the **newest on top**. Four fields, always:

### `<YYYY-MM-DD HH:MM UTC>` — `<your name / pod>`
- **Changed:** what landed this session (files, contracts, tests — be specific)
- **Frozen:** what must NOT change now, and why
- **Blocked:** what you're waiting on, and from whom
- **Attack next:** what the OTHER pod should build, test, or verify next

---

### 2026-09-02 13:34 UTC - teakeycee - CLOSE

- **Changed: the pipeline placed a real order.** Live SPY chain -> screener ->
  governor -> ledger -> executor -> Alpaca -> ledger follow-ups, on the **DEV**
  paper account, in **autopilot** mode with the governor as the sole gate. It
  filled. Ten commits this session.
  **The chain, folded by `root_id`:**
  `20260902T133336Z-f5591959a5` `approved_pending` -> `+01-submitted` (broker
  order `91657c8a-c2e8-4c44-9107-08a460e20960`) -> `+02-filled`, qty 1 at a net
  **-1.45** against a -1.43 limit. **`replay_root` on the root behind that
  position returns `matched=True`** — the verdict that produced a REAL position
  re-derives from the entry's own embedded proposal, account state and clock.
  Alongside it, one **terminal governor rejection**: computed max loss
  **151,944.00** against a 62,500.00 cap, coverage short by 52,400.00, cash floor
  breached to -51,944.00, and **`claim_divergence=151,694.00`** — the governor
  rejected on its own arithmetic and read the strategist's 250.00 claim only to
  write down how wrong it was.
  **Two modules landed with their suites: GB-D (data layer) and GB-E (executor).**
  `glassbox/datafeed.py` — 2b RAW only (no `reserved_*`, A2 b), no clock, no
  hand-rolled calendar, injectable transport, paper guard at the loader AND at
  every request. `glassbox/executor.py` — structure-tagged constructors where
  **the naked case is a `TypeError`, not a validation message**, 4a/4b wire
  mapping, `client_order_id` = prefix + ROOT id, and a duplicate resolved to the
  existing order rather than a second position. **No new dependencies**;
  `alpaca-py` was already pinned. `GB_INTERFACES.md` was **NOT** touched in any
  of the ten commits.
- **Tests: 132 passed, 1 skipped (the opt-in live band), 0 xfailed, 0 xpassed.**
  All five suites fully armed: GB-S 17, GB-C 34, GB-L 27, GB-D 29, GB-E 23 (+2
  probes). No assertion was changed to make any module pass; both new modules
  were written to their suites and armed on the first run.
- **LEADS RELEASED.** I took the **data layer** lead at 11:35 and the **executor**
  lead at 12:20, both by declaration. **Both go back to Jhoosier with this
  block.** Everything I did to the executor is contract-conformant to seam 4/4a/4b
  and covered by GB-E; the **MCP transport is untouched and still yours**.
- **DEV ACCOUNT IS NOT FLAT — deliberately, and per teakeycee's instruction.**
  Surviving position: **short 1x `SPY260903P00762000`, long 1x
  `SPY260903P00757000`** (a 762/757 put credit vertical, 5 wide, opened for 1.45).
  Max loss 357.00, fully defined. **It expires tomorrow, 2026-09-03**, inside the
  scored bound that selected it, and resolves itself at expiry with no action
  needed. Cash 100,000.00 -> 100,144.95. Do not close it to tidy up: it is the
  first governed position this system has ever taken and the ledger chain
  documents it.
- **EVENT_FACTS refreshed from Alpaca's official FAQ** (human export, read by me,
  recorded `[primary]` ✅ verified 2026-09-02). **The binding scoring fact:
  scoring reads TOTAL ACCOUNT EQUITY, not cash, at EOD Thursday 2026-09-03**,
  with that day's exercises and assignments reflected. The FAQ also mentions a
  Friday 09:30 snapshot; the two readings differ by one overnight and **we plan
  to the conservative one**. A short premium position still open after the bound
  is scored at its **mark**, not at the premium collected — so positions must
  resolve on or before Sep 3 to convert premium into scored equity. That is now
  `max_expiry_date = 2026-09-03`, **DECIDED** (not PROPOSED), in
  `config/thresholds.governor.SCORED.json`, enforced by the governor's
  `x_max_expiry` check and by clamping the data layer's fetch window to it.
  Also recorded: the official window was **Mon Aug 31 09:30 ET -> Fri Sep 4 09:30
  ET** and the agent was expected to start trading the competition account at the
  Aug 31 open — **we are starting late**, which costs scored days but is not
  disqualifying. **Judged on P&L plus creativity, autonomy, and robustness** — P&L
  matters but not alone. **An SDK is allowed if the reasons are explained and
  official SDKs are prioritized** -> `docs/EXECUTION_RATIONALE.md`. **Pre-event
  work is permitted but must be disclosed in the README** -> done, in full.
- **THE DASHBOARD IS NOW OPTIONAL, by primary source.** The FAQ says **no UI is
  required** and hosting matters only if a demo app is submitted. Jay, this is the
  thing I argued for last night on judgement and now do not have to: ranking the
  dashboard behind the strategist and the video is supported by the rules, not by
  my opinion. `SUBMISSION.md` items 9 and 10 should be reconsidered in that light
  — that is your call, not mine.
- **Frozen:** **`GB_INTERFACES.md` — both-humans rule, unchanged, and now four
  landed modules depend on it.** **`max_expiry_date = 2026-09-03` is DECIDED and
  frozen for the scored run** — it is a scoring-mechanics bound, not a trading
  judgement, and moving it changes what gets fetched, screened and approved.
  **Every other threshold in every config remains PROPOSED and uncalibrated.**
  **Competition keys stay out of every `.env` until the deliberate first-trade
  session.** The pinned 3a core `checks[]` vocabulary and the shape 5 status
  vocabulary both remain closed to me: the new expiry rule rides `x_max_expiry`
  precisely because the core list had no home for it.
- **Blocked:** Nothing on my side.
- **Seam amendments outstanding — all PROPOSED, none applied, one batch for one
  conversation. Six carried forward, one new:** (1) `malformed_record` as a sixth
  screener reason code; (2) refresh the stale shape-6 blockquote; (3) print the
  governor's ledger-derived `ledger` block in 2b's composed view; (4)
  `approved_pending` as a root status; (5) `corrects` as a nullable field on every
  entry; (6) the composition of `snapshot` as `{account_state, clock}`. **NEW (7):
  a screener reason code for a contract outside the scored expiry bound.** Today
  the bound is enforced by clamping the fetch and by the governor, so no late
  contract ever reaches the screener — but if one did, the screener would accept
  it, because none of its five codes honestly says "expires too late" and
  inventing a sixth unilaterally is the thing the both-humans rule exists to stop.
- **Two debts I am naming rather than hiding.** (a)
  `config/thresholds.governor.SCORED.json` duplicates every governor tunable
  except the bound, because the GB-C reference config is frozen golden data —
  putting Sep 3 in it would retroactively reject 18 hand-authored verdicts.
  `GB-C-F07` asserts the two files agree on every shared key, so a drift is a test
  failure rather than a discovery; **one calibrated config replacing both is a
  both-humans decision** because it changes what the golden fixtures mean. (b) The
  governor's **composed account view is still built in `scripts/dry_run.py`**;
  A2(b) assigns it to the governor and it belongs in `glassbox/governor.py` with
  GB-C criteria of its own. It is there because promoting it would add uncovered
  code to an armed module.
- **Attack next — Jhoosier, in this order.**
  **FIRST, the MCP strategist path.** **Autonomy is explicitly judged** (FAQ), and
  the scored run is **autopilot with the governor as the sole gate** — so the
  thing that turns this from a governed pipeline into an *agent* is the strategist
  proposing without a human choosing the strike. The seam it must produce is shape
  2 and nothing else; `demo/ledger_sample.jsonl` shows exactly what a proposal
  looks like on both sides of a verdict. **The governor is deterministic and has
  no prompt** — `prompt_version` goes on the ledger entry, never on the verdict —
  and `x_max_expiry` will reject anything expiring after Sep 3, so the strategist
  should propose inside that bound rather than discover it.
  **SECOND, the video.** It has a real hero moment now: a governor rejection with
  `claim_divergence=151,694.00`, and a real filled position whose decision
  replays.
  **THIRD, the dashboard, ONLY if time remains** — it is optional per the FAQ.
  `load()` -> `fold_chain()` per root -> `current_status()`; fold by `root_id`
  never by adjacency, and `partial_fill` is not an end state. `demo/README.md`
  spells it out.
  **And still the highest-value thing you could write: adversarial proposals
  against the governor.** Known gaps in my own coverage: a `claimed_max_loss`
  *higher* than computed, mismatched-expiry or multi-underlying legs, and a credit
  vertical priced wider than its own wings.
- **The competition account is a SEPARATE, human-ordered session on my side
  today.** Nothing in this session touched it and no competition key has been
  loaded anywhere. Given the Aug 31 expected start and the Thursday-EOD equity
  read, the first governed trade there wants to happen **today**, not Thursday —
  I will run it deliberately, with keys loaded for that session only, and it will
  go through this same pipeline in autopilot with the governor as the gate.

---

### 2026-09-02 12:20 UTC - teakeycee - OPEN

- **Data layer LANDED**, GB-D armed: **102 passed, 1 skipped (live band), 2
  xfailed.** The two xfails are `GB-D-F04` and `GB-D-11`, strict-xfail on the
  **absence of `tests/fixtures/datafeed/clock_open.json`** — `/v2/clock` reports
  one state at a moment and the market was closed when the fixtures were
  recorded. They arm the instant the file is recorded, which happens at today's
  open; nothing is derived from the closed clock and no assertion is relaxed.
- **Also taking EXECUTOR lead for today**, alongside the data layer lead I took
  at 11:35. **Both released back to Jhoosier at my CLOSE.** Reason: with the
  data layer landed, the executor is the last piece between the ledger and a
  real order, and I have the hours today to close it contract-first.
- Next, in order: EVENT_FACTS refresh from Alpaca's official FAQ; the scored-run
  expiry bound; the GB-E executor suite and module; then at the open, the clock
  recording, the live dry run, and one real governed order on the DEV account.

---

### 2026-09-02 11:35 UTC - teakeycee - OPEN
- **Taking DATA LAYER lead for today, releasing it back at my CLOSE.** Reason:
  six spare hours; the data layer is the critical path to an end-to-end dry run
  before Thursday's open. Per `HANDOFF_PROTOCOL.md` ("leads rotate by
  declaration in a HANDOFF block, nothing more formal"), this block is the
  declaration and it is pushed before the work starts.
- **Executor: I will contribute the seam 4a/4b structure-tagged constructors as
  a CONTRIBUTION, not a lead change; MCP transport stays yours.**
- Today's intent: GB-D contract suite against RECORDED fixtures (never the
  network), `glassbox/datafeed.py` to conform, then an end-to-end dry-run
  harness — chain -> screener -> governor -> ledger — on the DEV account with
  **no order submission of any kind**.

---

### 2026-09-02 11:27 UTC - teakeycee - CLOSE
- **Changed:** **Three modules landed, three suites armed: 75 passed, 0 xfailed,
  0 xpassed** — GB-S 17, GB-C 31, GB-L 27 (7 fixture-integrity + 20 behaviour).
  Two commits this session, on top of the four in my 10:30 and 10:55 blocks.
  (1) `GB-L ledger contract suite + golden entries` — `tests/fixtures/ledger/`
  with **`entries.jsonl`: 18 entries, 6 chains** per shape 5 and 5a (A: root →
  submitted → partial_fill → filled; B: a governor rejection, complete and
  terminal at the root; C: root → submitted → broker_rejected → **correction**;
  D: canceled; E: expired with `prompt_version` **null**, hand-authored, no LLM;
  F: **still in flight** at partial_fill) and `expected_chains.json` carrying the
  golden fold. The embedded proposals, account states, clocks and verdicts are
  **the governor's own golden fixtures**, so every entry is a real decision by
  the real governor — and **GB-L-F05 cross-checks each embedded verdict against
  the GB-C hand-authored `checks` map**, which is where the circularity stops.
  (2) `Ledger writer + replay land, GB-L armed and green` —
  **`glassbox/ledger.py`**: writer (`Ledger(path)` with `append_root`,
  `append_follow_up`, `append_correction`), reader (`load`, `list_roots`,
  `fold_chain`, `current_status`, `is_terminal`), `client_order_id`, and the
  **replay helper**. **No new dependencies.**
  **Append-only is enforced by the API:** `update()` and `delete()` exist and
  raise `AppendOnlyError`, so the rule is discoverable where someone reaches for
  it. A correction appends and **the corrected entry stays in the file, byte for
  byte**. **The writer holds no clock** — `ts` is passed in — and storage is a
  caller-supplied JSONL path with no module state and no default location.
  **Chains fold by `root_id`, never by adjacency**: the golden file interleaves
  them on purpose, so a fold that walks forward from a root until it meets the
  next root gets four of six chains wrong. **`partial_fill` is non-terminal.**
  **Replay is the point of the module, and it is the provenance claim made
  executable.** `replay_root` re-derives a root entry's verdict by re-running the
  governor on **the entry's own embedded proposal, account state and clock** —
  nothing outside the entry is consulted except the config it names, and
  replaying under a different `config_version` **raises** rather than passing a
  match off as a reproduction. All six golden decisions replay identically. **A
  verdict flipped to approved does not, and neither does a doctored input**
  (GB-L-16) — a replay that cannot fail proves nothing. Serialization is
  deterministic (shape 5 key order, sorted nested keys, ISO-8601 UTC, one entry
  per line) and GB-L-11 re-serializes every golden entry and requires the bytes
  back, so a diff of a ledger means a change in the facts.
  Two defects the suite caught and **the module** fixed: `append_root` now states
  every shape 5 field including `order`/`fill`, and a docstring that spelled out
  an order-id prefix literal was reworded — GB-L-07 greps the package for exactly
  that. One scaffolding fix I stopped and cleared with you first: the GB-L arming
  probe named a module-level `append_root` no test uses; it now names `Ledger`.
  No assertion changed anywhere. **`GB_INTERFACES.md` was NOT touched.** No
  orders; dev account untouched and flat.
- **Next on my side: an end-to-end DRY-RUN HARNESS** — a hand-authored proposal →
  screener → governor → ledger, against the **dev** account, with **no strategist
  and no UX required**. Every piece it needs now exists and is armed. That gives
  us a **governed trade path that actually runs**, so the competition account has
  one ready for **Thursday's open** rather than a pipeline that has only ever been
  exercised by tests.
- **A proposal about tonight's freeze — please read this one.** I think we should
  treat it as a **FEATURE freeze, not a wiring freeze.** Nothing new gets
  proposed after tonight; **integration continues**, because right now the three
  modules I own have never run against anything but fixtures, and the two you own
  have never met them. Freezing the wiring tonight freezes us at "three green
  suites and no trade", which is the wrong artefact to submit on Sep 4. If you
  disagree, say so in your next block and I will hold — but I would rather spend
  Wednesday connecting what exists than adding to it.
- **Frozen:** **`GB_INTERFACES.md` — both-humans rule, unchanged.** **All three
  threshold/config files remain PROPOSED and uncalibrated**:
  `thresholds.PROPOSED.json` (screener), `thresholds.governor.PROPOSED.json`
  (governor), and the golden `config_version` the ledger fixtures carry. The
  pinned 3a core `checks[]` vocabulary and the shape 5 status vocabulary are both
  closed to me: the ledger's writer **refuses** a status it was not given, so the
  vocabulary cannot grow by accident in a crunch.
- **Seam amendments outstanding, all PROPOSED, none applied — carried forward and
  added to:** from 10:55, (1) `malformed_record` as a sixth screener reason code,
  (2) refresh the stale shape-6 blockquote, (3) print the governor's
  ledger-derived `ledger` block in 2b's composed view. New tonight, all in shape
  5: (4) **`approved_pending` as a root status** — 5a requires the root written
  **pre-submission** and the vocabulary has no value for "approved, not yet
  submitted"; every value it does have describes a rejection or a state an order
  is already in. (5) **`corrects` as a nullable field on every entry** — the seam
  says a correction "references the id of the entry it corrects" but gives it no
  field, and `root_id` cannot carry it because that is the fold key. (6) **the
  composition of `snapshot`** as `{account_state, clock}`, which shape 5 leaves as
  an open object — this is exactly what replay needs, and without pinning it the
  provenance claim is not checkable. All six are one batch for one conversation.
- **Blocked:** Nothing on my side.
- **Attack next:** **Jhoosier — order matters tonight, so here it is explicitly.**
  **FIRST, the data layer and the executor.** They are the **two pieces between my
  three modules and a real order**, and nothing else you could build changes that.
  Data layer: shape 6 inputs and **shape 2b RAW broker state** (raw only — the
  governor now **raises** if handed a raw state where its composed view belongs,
  GB-C-21, so A2 (b) is enforced from both ends), plus `clock()` and `calendar()`
  feeding `market_open`. Executor: **4a/4b** — single-leg `covered_call` /
  `cash_secured_put` are **not `mleg`**, wire `limit_price = abs(net_debit_credit)`
  with direction from `side`, **never a negative limit on a single-leg order**;
  `position_intent` on every leg, opening-only; **`client_order_id` = your
  `ORDER_ID_PREFIX` + the ROOT ledger entry id** — `glassbox.ledger.client_order_id()`
  builds it, reads the env var, and **raises if unset**, so import it rather than
  formatting the string yourself.
  **SECOND, the dashboard reads the ledger JSONL directly** — `load()` then
  `fold_chain()` per root, and render `current_status()`; **fold by `root_id`, and
  do not treat `partial_fill` as an end state.** `tests/fixtures/ledger/entries.jsonl`
  is a complete, realistic file you can build against right now with no data layer
  and no broker.
  **THIRD, and deliberately last: the strategist and the NL UX.** They are the
  opener and they matter for the video — but **the ledger and one governed trade
  are the proof**, and a demo that shows a beautiful intent box in front of a
  pipeline that has never placed an order is the version of this project that
  loses. When you get to the strategist, **attack the governor with adversarial
  proposals** — still the highest-value fixtures either of us can write, and still
  your lane. The gaps I know about in my own coverage: a `claimed_max_loss`
  *higher* than the computed figure, mismatched-expiry or multi-underlying legs,
  and a credit vertical priced wider than its own wings.

---

### 2026-09-02 10:55 UTC - teakeycee - CLOSE (freeze day)
- **Changed:** **Both of my modules are landed with their suites armed and green:
  48 passed, 0 xfailed, 0 xpassed — GB-S 17 (4 fixture-integrity + 13 behaviour),
  GB-C 31 (6 fixture-integrity + 25 behaviour from 21 criteria).** No test was
  changed to make either module pass; both were written to their suite, and both
  strict-xfail bands deactivated on their own. Four commits this session — the
  two screener commits are in my 10:30 block; the two new ones are:
  (1) `GB-C governor contract suite + golden fixtures` — `tests/fixtures/governor/`
  with `thresholds.governor.PROPOSED.json` (per-structure `max_loss_cap`,
  `cash_floor_pct`, churn window + min hold, position caps, net tolerance — every
  number PROPOSED and uncalibrated, `covered_call`'s cap deliberately `null`),
  **10 proposals** per shape 2 covering every structure in the closed enum plus
  the defects, **12 account states** per shape 2b with `raw_` (data layer, A2 b)
  and `composed_` (governor's view) kept strictly apart, **open and closed
  `/v2/clock` fixtures** for 6c, and **18 golden cases, 4 approve / 14 reject**,
  each stating every check in the pinned 3a vocabulary plus the expected computed
  max loss. `tests/test_governor_contract.py` names criteria **GB-C-F01..F06 and
  GB-C-01..21**; conftest's module probe is generalised over both suites and the
  OCC regex moved there so the two suites read one definition.
  (2) `Governor lands, GB-C armed and green` — **`glassbox/governor.py`**,
  `govern(proposal, account_state, clock_or_as_of, thresholds, mode,
  config_version) -> verdict`. Pure: no clock (`as_of` comes from the clock it is
  handed), no randomness, no file I/O, no defaults — a missing threshold key
  raises. **No new dependencies.**
  What it enforces, and the fixtures that hold it to it: **max loss is computed
  from strikes / `ratio_qty` / `qty` / net price per structure, and
  `claimed_max_loss` is read ONLY to record the divergence** — the false-claim
  case claims 200 against a computed **819** and a 500 cap, and is rejected on the
  computed figure with `claim_divergence=619.00` in the detail. **`structure_valid`
  tests the declared structure against actual leg composition**, so a lone short
  call labelled `vertical_spread` fails — that is the half of 2e that lives in the
  governor. **`net_reconciles` is the C1 per-share sum with `qty` deliberately
  absent**, and it names the qty-factor mistake in the detail when it sees one.
  **`structure_valid` and `net_reconciles` are gates:** if either fails the risk
  band is recorded failed and `not evaluated`, because risk math on numbers just
  declared untrustworthy is worse than no number — while `churn_guard`,
  `market_open` and `x_position_cap` still run, so the verdict stays a full audit
  record rather than an early exit. **Coverage is measured against UNRESERVED
  collateral**, verticals against the computed max loss. **Every check carries its
  numbers in the seam's `key=value` detail convention, including checks that
  passed.** Position caps ride `x_position_cap` per the 3a hybrid — no new core
  vocabulary invented. **`GB_INTERFACES.md` was NOT touched in any of the four
  commits.** No orders; dev account untouched and flat.
- **Next on my side:** the **provenance ledger writer** per seam 5a — root entry
  written pre-submission with `order: null` / `fill: null` so `client_order_id`
  can embed its `id`, follow-ups appended on `root_id`, nothing ever mutated.
  That is the block after this one.
- **Frozen:** **`GB_INTERFACES.md` — both-humans rule, unchanged, and it is freeze
  day, so the bar is higher not lower.** Both threshold files are **PROPOSED and
  uncalibrated** — `thresholds.PROPOSED.json` (screener) and
  `thresholds.governor.PROPOSED.json` (governor). Every governor number was chosen
  so a fixture sits unambiguously on one side of it; **none of them is a trading
  judgement** and the real config must supersede both before anything trades. The
  pinned 3a core `checks[]` vocabulary is closed to me: `x_` is the only extension
  I may add without you.
- **Seam amendments proposed, batched for both humans — NOT applied:**
  1. **Add `malformed_record` as a sixth screener reason code (shape 6).** Today a
     schema violation in a contract record — no symbol, unparseable strike, a
     `type` that is neither call nor put — **raises**. That is fail-closed for the
     run, and deliberate: none of the five codes would honestly describe a broken
     record. But a raise leaves **no ledger entry**, so a malformed record is
     invisible to the audit trail, which is the one thing this system is claiming
     to have. A sixth code turns it into a rejection we can count.
  2. **Refresh the stale shape-6 blockquote.** It still says the `missing_ask`
     counter-fixture is "not yet in the fixtures" and that "the seam is the
     authority" pending it. The fixtures caught up at 10:30 today; the note
     describes a gap that is closed.
  3. **(Smaller, mine this session — flagging it rather than letting you find it.)**
     My `composed_` account fixtures carry a **`ledger` block**
     (`open_positions`, `recent_activity{last_open_at, position_opened_at}`) that
     2b's composed view does not print. Same provenance as
     `reserved_cash`/`reserved_shares` under A2 (b) — **governor-derived from the
     ledger, never from the data layer** — and `churn_guard` and `x_position_cap`
     cannot be computed without it, since the entry point takes no ledger argument.
     **It does not cross the seam, so it is not a change to anything you build**,
     but 2b prints the composed view, so printing it there is yours to agree to.
     Also mine and also PROPOSED: the **`cash_floor` arithmetic** and the two
     **`churn_guard` inputs**, which 3a names but does not define. Both are written
     up in `tests/fixtures/governor/README.md` for you to attack.
- **Blocked:** Nothing on my side.
- **Attack next:** **Jhoosier** — (1) **data layer** against the signed seam:
  shape 6 inputs (contracts with the `expiration_date_gte/lte` filter, snapshots
  at `feed=indicative`) and **shape 2b RAW broker state** — raw only, no
  `reserved_cash` / `reserved_shares`; the governor now **raises** if handed a raw
  state where its composed view belongs, which is GB-C-21, so the two halves of
  A2 (b) are enforced from both ends. `clock()` and `calendar()` pass-throughs
  feed `market_open` directly. (2) **Executor constructors per 4a/4b:** single-leg
  `covered_call` / `cash_secured_put` are **not `mleg`**, wire `limit_price =
  abs(net_debit_credit)` with direction from `side`, **never a negative limit on a
  single-leg order**; `position_intent` on every leg, opening-only for this event;
  `client_order_id = <ORDER_ID_PREFIX from your .env><ledger-entry-id>`, prefix
  never hardcoded. (3) **Attack the governor with adversarial proposals — this is
  the highest-value thing either of us can do today and it is squarely your lane,**
  because you own the strategist and the strategist is what the governor exists to
  distrust. Both suites are armed, so a proposal that should be refused and is not
  is a red test rather than an argument. Where I would aim: a proposal whose legs
  reconcile but whose `structure` is a lie in a way my six structure fixtures do
  not cover; ratio spreads that are 1:1 by GCD but not by risk; a credit vertical
  priced at a credit wider than its own wings; multi-underlying or mismatched-expiry
  legs; and anything where `claimed_max_loss` is *higher* than the computed figure
  rather than lower, which none of my fixtures test. Screener side, the two I still
  want hit are **pagination** and **any partial-greeks reality**.

---

### 2026-09-02 10:30 UTC - teakeycee - CLOSE
- **Changed:** **The chain screener has landed and the GB-S suite is ARMED and
  GREEN: 17 passed, 0 xfailed, 0 xpassed.** No test was changed to make it pass;
  the strict-xfail band deactivated on its own when the module appeared. Two
  commits.
  (1) `Fixtures: five-code vocabulary, missing_ask case + GB-S test` — the gap
  the sign-off commit knowingly left is **CLOSED**. New counter-fixture
  **`SPY260918C00760000`** (far-OTM call, complete greeks, quote fresh at 25 s,
  real 0.04 bid, offer pulled: `ap: 0, as: 0`), isolated so `missing_ask` is the
  only thing between it and acceptance and a mislabel as `missing_bid` fails the
  suite. `expected_verdicts.json` now names **all five codes** and the new
  contract as `reject ["missing_ask"]`; the slice is **8 contracts, 2 accept /
  6 reject**. `conftest.has_ask()` added mirroring `has_bid()`; **GB-S-13**
  asserts rejection under that code specifically; **GB-S-F03** proves the new
  defect is present and isolated. Fixtures README: the missing-ask trap is now
  trap 2 (rest renumbered), slice table updated, and a new **"Reason-code
  vocabulary — the seam is the authority"** section records that the fixtures
  mirror `GB_INTERFACES.md` shape 6 and never define it. Both test-module
  docstrings corrected — they still described the seam as frozen pre-sign-off
  and screener-less.
  (2) `Screener: screen_chain lands, GB-S suite armed and green` —
  **`glassbox/screener.py`** exposing `screen_chain(contracts, snapshots, as_of,
  thresholds)` per shape 6, plus a minimal `glassbox/__init__.py` and a
  `pytest.ini` putting the repo root on `sys.path` (conftest probes for the
  module at import time, so it has to be config, not test setup). **No new
  dependencies; `requirements.txt` unchanged.** Pure by contract: no file I/O
  (the caller loads thresholds and passes the mapping in per 6a — **no built-in
  defaults, a missing key raises**), no clock (age is `as_of - quote.t`, 6b), no
  randomness. Every input contract lands in exactly one output list, in input
  order; reasons come out in the seam's vocabulary order. Fail-closed decisions
  worth your attack: a quote dated **after** `as_of` is rejected `stale_quote`
  rather than treated as very fresh; a snapshot whose quote is absent or
  unparseable is rejected, not given the benefit of the doubt; a greek must be a
  **finite number** (None, absent or non-numeric fails); `bp/bs` and `ap/as`
  zero pairs read as NO BID / NO ASK, never $0.00. **Data quality is rejected
  with a code; a schema violation raises** (no symbol, unparseable strike, a
  `type` that is neither call nor put) — the five-code vocabulary is closed and
  none of them would honestly describe a broken record. Verdict counts over the
  full slice: `null_greeks` 2, `missing_bid` 2, `missing_ask` 1, `stale_quote`
  1, `no_snapshot` 1 — 7 codes across 6 rejected contracts, matching the golden
  file symbol by symbol. **`GB_INTERFACES.md` was NOT touched.** No orders; dev
  account untouched and flat.
- **Frozen:** **`GB_INTERFACES.md` — both-humans rule, unchanged.** One
  consequence to note rather than fix unilaterally: the seam's blockquote under
  shape 6 saying the `missing_ask` counter-fixture is **"Not yet in the
  fixtures"** and that "the seam is the authority" **is now stale** — the
  fixtures caught up this session. It is a note about a closed gap, not a field
  change, and the fixtures README records the closure; **striking it from the
  seam still needs both of us**, so I left it. `thresholds.PROPOSED.json` is
  **still PROPOSED and uncalibrated** — `quote_max_age_seconds: 300` remains a
  placeholder chosen to separate the fixtures, not a trading judgement, and
  nothing trades until a real config supersedes it. The screener's five-code
  vocabulary is closed: extra codes need the seam first.
- **Blocked:** Nothing on my side. Next on me is the **GB-C governor contract
  suite**.
- **Attack next:** **Jhoosier** — (1) the **data layer** against the signed
  seam: emit **shape 6 inputs** (`/v2/options/contracts` bodies with the
  `expiration_date_gte/lte` filter, `/v1beta1/options/snapshots` at
  `feed=indicative`) and **shape 2b raw account state** — raw broker state only,
  no `reserved_cash` / `reserved_shares`, those are governor-derived from the
  ledger per A2 (b). `clock()` and `calendar()` pass-throughs still needed for
  6c. (2) **Attack the screener with counter-fixtures from your live-test
  notes.** It is armed, so a fixture that should reject and does not is now a
  red test rather than an argument. The two places I most want hit are
  **pagination** (my slice is single-page with `next_page_token: null`; the real
  endpoint paginates nearest-expiry-first, and I do not consume the token —
  decide with me whether paging belongs in the data layer or the screener) and
  **any partial-greeks reality**: my fixtures assume `greeks` is either null or
  complete, and if the live feed ever returns a greeks object with one null
  member, I want your capture. Symbols absent from `snapshots`, future-dated
  timestamps, and non-numeric greeks are all handled — try to break them anyway.

---

### 2026-09-02 10:20 UTC - teakeycee - OPEN
- **Changed:** **The seam is SIGNED and SWAPPED. `GB_INTERFACES.md` is IN FORCE
  as of 2026-09-02**, supersedes all prior versions, and changes now require
  both humans. `GB_INTERFACES.SIGNOFF-DRAFT.md` is deleted; there is one file of
  record again. Two commits: (1) every `OPEN (sign-off)` marker converted to
  `DECIDED (2026-09-02)` — A1 Option B (`iron_condor` out of the enum; a condor
  is a strategist-level composition of two `vertical_spread` proposals and never
  crosses the seam as one structure), A2 (b) governor-maintains-reservations
  from the ledger with the data layer reporting raw broker state only, A3 hybrid
  with the core `checks[]` vocabulary pinned (`structure_valid, net_reconciles,
  max_loss_cap, coverage, cash_floor, churn_guard, market_open`; extras under
  `x_`), A4 (c) append-only chains with `root_id`, `submitted` added and
  `partial_fill` marked non-terminal, A5 (a) + `market_open` as a submission-gating
  governor check; (2) the human-ordered swap plus a minimal `CLAUDE.md`
  alignment line naming the seam of record and the pinned checks vocabulary.
  **C1-C4 CONFIRMED and applied** — they are wire-format facts, not preferences:
  C1 per-share reconciliation with the `qty` factor dropped
  (`net = sum(sign(action) * limit_price * ratio_qty)`, dollars = `net * 100 * qty`
  computed by the governor only), C2 `ratio_qty` on legs with GCD 1 enforced in
  `structure_valid` and `qty` at proposal level, C3 covered call / CSP are
  single-leg orders not mleg with wire `limit_price = abs(net)` and direction from
  `side`, C4 `position_intent` on order legs, opening-only for this event.
  **`missing_ask` adopted** into the shape 6 reason vocabulary. Both signatures
  recorded in the change log: teakeycee signed 2026-09-02; Jhoosier accepted per
  `docs/SIGNOFF_REVIEW_jhoosier.md` and his 06:10 UTC block.
  **Initial leads are now ACTIVE** per the seam's lead table — teakeycee: chain
  screener, governor + contract suites, provenance ledger, strategist prompt
  review; Jhoosier: data layer, MCP executor, LLM backend + strategist, NL intent
  UX, dashboard, video + deck; Telegram digest OPTIONAL (stretch), lead
  unassigned. No code, tests, or fixtures touched. No orders; dev account flat.
- **Frozen:** `GB_INTERFACES.md` is IN FORCE — not frozen against use, frozen
  against unilateral change: **any field change needs both humans, here first,
  before code depends on it.** The `missing_ask` fixture and test are NOT in this
  commit; `tests/fixtures/expected_verdicts.json` still names four codes while the
  seam names five, and the seam is the authority until my screener session lands
  the fifth. `thresholds.PROPOSED.json` still uncalibrated.
- **Blocked:** Nothing on me. Sign-off is closed.
- **Attack next:** **Jhoosier pod is GO on the data layer against the signed
  seam** — account/positions/open orders, `clock()` + `calendar()` pass-throughs
  (A5 depends on them), contracts with the expiration filter, snapshots failing
  closed on null greeks. Note A2: your shape 2b output carries raw broker state
  only, no `reserved_cash` / `reserved_shares` — the governor derives those from
  the ledger. I'm building the **chain screener** today with `missing_ask` and the
  counter-fixture, GB-S arming expected. **Freeze is tonight** — anything not in
  flight by my CLOSE stays out of scope for this event.

---

### 2026-09-02 06:10 UTC - Jhoosier - OPEN
- **Changed:** Documentation only. (1) `docs/F2_wire_check.md`: F2 verified
  against Alpaca's SDK reference and Level 3 guide. Sign convention matches
  the wire (positive = debit, negative = credit); units are per-share, one
  unit of spread, multiplier and qty applied downstream. Four amendments:
  C1 reconciliation rule drops the qty factor; C2 legs carry `ratio_qty`,
  `qty` moves to proposal level; C3 covered call / CSP are single-leg orders
  (not mleg), wire limit is abs(net) with direction from `side`; C4 order
  shape gains `position_intent`. (2) `docs/SIGNOFF_REVIEW_jhoosier.md`:
  Jhoosier accepts F1(c), F3 `missing_ask`, A1 Option B, A2 (b), A3 hybrid,
  A5 (a)+market_open, A7-A11 as proposed. B1: teakeycee's lead split
  accepted as proposed; Telegram digest is OPTIONAL/stretch. B2: Streamlit.
  B3: competition account CREATED 2026-09-02 by Jay on the bare team
  address: **PA3424LCNZBS**, $100k, options Level 3. Keys in the vault
  under a separate COMPETITION entry; NOT in any .env yet. Every box keeps
  pointing at the dev account until GB-S + GB-C pass. No manual orders on
  it, ever. SUBMISSION.md row 11 updated.
  GB_INTERFACES.md and GB_INTERFACES.SIGNOFF-DRAFT.md untouched.
- **Frozen:** `GB_INTERFACES.md` still the file of record until both sign.
  tests/, fixtures, thresholds.PROPOSED.json untouched. Dev account flat.
- **Blocked:** teakeycee's confirmation of C1-C4 and signature.
- **Attack next:** teakeycee: read docs/F2_wire_check.md, confirm C1-C4,
  sign the draft's change log. Then start the screener with `missing_ask`
  per your own order of work; the data layer's snapshot fixture shape is
  the one already in tests/fixtures. Jhoosier side starts the data layer as
  soon as the swap is done.

### 2026-09-01 10:00 UTC - teakeycee - OPEN
- Verification gate run on US box: a, b, c1, c2 all PASS. GATE GREEN.
  Phase 3 DONE-WHEN now closed on both sides.
- CLAUDE.local.md created on the US box per your pod-identity split; the
  pod-neutral CLAUDE.md rewrite is adopted as-is. One alignment note for
  sign-off: CLAUDE.md build rules still say iron-condors-as-two-verticals
  is settled while agenda A1 reopens it; whichever way A1 goes, that line
  gets updated to match.
- Today: reviewing GB_INTERFACES.SIGNOFF-DRAFT.md with signoff_agenda.md
  open, attack points first (A6 sign convention, A4/ledger status vocab vs
  Alpaca's actual order states, possible fifth screener reason code).
  Touchpoint-ready after review.


### 2026-08-31 04:55 UTC - Jhoosier - CLOSE
- **Changed:** Documentation only, no code/tests/fixtures touched. Two new files:
  (1) `GB_INTERFACES.SIGNOFF-DRAFT.md` at repo root — a complete proposed
  replacement for the frozen seam, prepared at your Attack-next request. Parties
  relabelled teakeycee / Jhoosier (Tiki/TKC retired); ownership table replaced
  with a CURRENT LEAD table, every row `set at sign-off`, leads rotating via
  HANDOFF per HANDOFF_PROTOCOL.md. Shape 2 proposal: `structure` closed to
  `covered_call | cash_secured_put | vertical_spread | iron_condor`; legs gain
  `symbol` (OCC) and the proposal gains `underlying` — without a symbol the
  governor's output cannot become an order; legs gain `limit_price` and the
  proposal `net_debit_credit` with a normative reconciliation rule (net must
  equal the signed sum of leg prices x qty or the governor rejects; the net is
  the executable figure since Alpaca multi-leg fills on a single net limit);
  `max_loss`/`max_gain` renamed `claimed_max_loss`/`claimed_max_gain`, ADVISORY,
  kept so the GB-C false-claim fixture has something to catch; explicit note that
  naked-short prevention is NOT a schema property (a covered call and a CSP are
  each a lone short leg — coverage is account state) and lives in the order
  builder's structure-tagged constructors plus the governor's
  structure-vs-legs-vs-account-state check. New shape 2b account state (per-
  underlying shares, cash, buying power, reserved cash/shares, `as_of`),
  PLACEHOLDER. Shape 3 verdict: `mode` (approve|autopilot), `config_version`
  recommended as a content hash rather than a hand-bumped string, the governor's
  independently computed max loss surfaced in `checks` detail, and
  `prompt_version` explicitly excluded (the governor is deterministic and has no
  prompt — it rides the proposal/ledger). Shape 4 order: `client_order_id`,
  prefix from `ORDER_ID_PREFIX` in each box's `.env` and never hardcoded
  (`tkc-`/`jho-` appear as marked examples only), scheme
  `<prefix><ledger-entry-id>` so a retried submit dedupes at the broker. Shape 5
  ledger: `order`/`fill` explicitly NULLABLE and never key-omitted; PROPOSED
  status vocabulary `governor_rejected | broker_rejected | filled | partial_fill
  | expired | canceled`; `id`, `as_of`, `config_version`, `prompt_version`,
  `code_version`, `mode`, `approved_by`/`approved_at` (null in autopilot);
  append-only rule stated. New shape 6: your `screen_chain(contracts, snapshots,
  as_of, thresholds) -> result` lifted verbatim from tests/conftest.py with the
  reason vocabulary from expected_verdicts.json, plus two normative notes — the
  CALLER loads thresholds and passes the mapping in (no file I/O, GB-S-10
  determinism, no component carries its own copy of a tunable), and freshness is
  measured against `as_of`, never wall clock (fixtures README trap #2). Your
  quote-freshness question is written up as 6c, PROPOSED + OPEN, not decided.
  Change log carries a dated entry with both signatures pending.
  (2) `docs/signoff_agenda.md` — one-page run-down of every OPEN item (iron
  condor representation, reservation producer, `checks[]` vocabulary, ledger
  status in flight, `as_of` policy) plus the SETUP 4.1 non-shape decisions
  (initial leads, demo platform, competition-account creator/timing ~Sep 1).
  **GB_INTERFACES.md itself was NOT touched.** No orders placed; dev account
  untouched and flat.
- **Frozen:** `GB_INTERFACES.md` remains FROZEN and is still the file of record
  until BOTH humans sign. The draft supersedes it only after sign-off, and the
  swap is a separate human-ordered step — no pod performs it. tests/ and
  tests/fixtures/ untouched this session; the GB-S suite and golden fixtures are
  exactly as you left them at 77714be. `thresholds.PROPOSED.json` still
  uncalibrated.
- **Blocked:** Sign-off needs teakeycee — nothing in the draft is decided, and
  six items are explicitly OPEN pending both humans. Your dev-keys request is
  CLEARED: Jay placed the ALPACA_API_KEY + ALPACA_SECRET_KEY values in the
  shared sheet ~2026-08-31 03:55 UTC (after your CLOSE block). Remaining on
  your side: fill .env from the sheet (plus ORDER_ID_PREFIX=tkc-), run
  scripts/verify_gate.py, and report a/b/c — Phase 3 DONE-WHEN needs both
  sides green.
- **Attack next:** teakeycee — FIRST: dev keys are in the shared sheet now;
  fill your .env and run the verification gate so Phase 3 closes before the
  touchpoint. Then review `GB_INTERFACES.SIGNOFF-DRAFT.md` against
  your live-test notes and the golden fixtures. Mark objections inline; the
  places most worth attacking are the reconciliation rule's sign convention, the
  ledger status vocabulary against what Alpaca actually reports, and whether the
  screener reason vocabulary needs a fifth code your fixtures imply but
  `expected_verdicts.json` does not yet name. Then come to the touchpoint ready
  to sign or amend, with `docs/signoff_agenda.md` open — it is built to be run
  down in order.

### 2026-08-30 22:07 UTC - teakeycee - CLOSE
- **Changed:** US environment green (venv, pinned deps incl. pytest==9.1.1); Claude
  Code relay operational; phase 1 complete as of commit adb1030 (CLAUDE.md,
  SUBMISSION.md, scripts/verify_gate.py, docs/handoff_protocol.svg, .env.example
  naming aligned: ALPACA_API_SECRET retired, use ALPACA_SECRET_KEY); GB-S screener
  contract suite + golden fixtures landed this commit: 7-contract SPY slice with
  isolated defects, golden verdicts with reason codes, 4 fixture-integrity tests
  passing, 12 behavior tests strict-xfail that auto-arm when a screener module with
  screen_chain() appears. Correction to my earlier block: SUBMISSION.md and
  docs/handoff_protocol.svg are no longer missing; both landed in adb1030.
- **Frozen:** GB_INTERFACES.md and TEAM_PROTOCOL.md untouched, pre-sign-off. The
  screen_chain(contracts, snapshots, as_of, thresholds) signature is PROPOSED and
  lives only in tests/conftest.py; it moves into GB_INTERFACES at sign-off, not
  before. thresholds.PROPOSED.json values (incl. quote_max_age_seconds: 300) are
  placeholders, not calibrated judgments.
- **Blocked:** Verification gate BLOCKED on dev keys — not yet in the shared sheet;
  ALPACA_API_KEY and ALPACA_SECRET_KEY are present but empty in this box's .env, so
  scripts/verify_gate.py was not run this session and the US-side a/b/c remains
  unverified. Phase 4 seam sign-off pending both humans.
- **Attack next:** paste dev keys to the sheet; pick the demo platform (Streamlit /
  Replit / Vercel); review the fixture shapes and GB-S criteria against your live-test
  notes and attack them with counter-fixtures if you see a gap; come to sign-off ready
  on: seam shapes (+ my proposed screen_chain seam), initial leads, competition
  account creator and Monday-if-ready timing, and one real design question: quote
  freshness vs closed markets. Any quote is hours old outside market hours, so a
  naive freshness rule rejects everything on weekends; we need deliberate as_of
  semantics or market-hours-only screening. This affects run scheduling and the
  scored P&L window, so it needs both humans.

### 2026-08-30 15:00 UTC - Jhoosier - CLOSE
- **Changed:** Phase 2 + Phase 3 gate complete on Japan side. Dev paper account live
  (PA34K04ZYHYO, $100k, options level 3 — spreads approved; credentials in the shared
  vault). Verification gate a/b/c ALL GREEN: (a) /v2/account 200; (b) SPY daily bars
  via free iex feed; (c) SPY options chain — /v2/options/contracts (expirations,
  strikes, OI) AND /v1beta1/options/snapshots (two-sided quotes + greeks/IV on
  near-the-money, feed=indicative) both work on the FREE PAPER TIER. The critical
  unknown is resolved: options data does not constrain the build; recorded as a
  [primary] row in EVENT_FACTS.md. Committed this session: HANDOFF_PROTOCOL.md,
  SETUP.md, docs/setup_plan.svg (NB: the local SVG turned out to be the setup-plan
  diagram, so it landed at that path; docs/handoff_protocol.svg is the one still
  missing), LICENSE (MIT), requirements.txt (all deps pinned, alpaca-py==0.44.0),
  alpaca-mcp.draft.json (Alpaca official MCP server config, keys blank — activate
  with `claude mcp add alpaca --transport stdio uvx alpaca-mcp-server` + env keys
  from vault; server expects ALPACA_SECRET_KEY, not .env.example's ALPACA_API_SECRET).
  Quirks for the screener: contracts endpoint paginates nearest-expiry-first (filter
  by expiration_date_gte/lte); greeks null on deep-ITM/illiquid strikes.
- **Frozen:** GB_INTERFACES.md + TEAM_PROTOCOL.md untouched (DRAFT shapes, pre-sign-off).
  Dev account left flat — gate was read-only, no orders placed.
- **Blocked:** Phase 4 seam sign-off (both humans): shapes, initial leads, demo
  platform pick, competition-account creator for ~Sep 1.
- **Attack next:** US side run its own a/b/c against the dev account from its box
  (Phase 3 DONE-WHEN needs both sides green), then prep seam sign-off. Chain-screener
  golden fixtures can start immediately — free-tier snapshot shape is confirmed.
  Still needed for Phase 1: SUBMISSION.md and docs/handoff_protocol.svg (setup_plan.svg
  exists; the handoff diagram is the missing one).

### 2026-08-28 00:00 UTC — SEED (replace this)
- **Changed:** repo created; coordination spine committed (this file, GB_INTERFACES.md, TEAM_PROTOCOL.md, EVENT_FACTS.md)
- **Frozen:** nothing yet
- **Blocked:** GB_INTERFACES.md seam needs both humans' sign-off before parallel build starts
- **Attack next:** confirm the module split in GB_INTERFACES.md, then wire the data layer + first fixtures
