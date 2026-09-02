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

### 2026-09-02 09:30 UTC - Jhoosier - CLOSE
- **Changed:** Data layer landed on branch `claude/jhoosier-data-layer-2evft4`
  (Jhoosier lead per B1). New package `glassbox/` (`__init__.py`,
  `data_layer.py`). Built against the sign-off draft plus the Jhoosier
  review positions: A2 (b), A5 (a), F2 C1-C4; draft PLACEHOLDER names kept
  as written. Surface: `AlpacaClient(api_key, secret_key, trading_base_url,
  data_base_url)` + `from_env()` (reads ALPACA_API_KEY / ALPACA_SECRET_KEY /
  ALPACA_TRADING_BASE_URL / ALPACA_DATA_BASE_URL; refuses a non-paper
  trading URL by raising; missing keys raise naming the variables; timeout
  15 s; non-200 raises `DataLayerError` with status + body excerpt).
  Raw pass-throughs: `get_account` (+`as_of`), `get_positions`,
  `get_open_orders` (nested legs), `get_clock`, `get_calendar`.
  `get_contracts` / `get_snapshots` follow `next_page_token` and return the
  exact fixture shapes: numerics stay strings on contracts, null greeks
  pass through as null, absent symbols stay absent (screener's
  `no_snapshot`). `get_snapshots(symbols=...)` uses the by-contract endpoint
  `/v1beta1/options/snapshots?symbols=` (same body shape); without symbols
  it is the per-underlying chain endpoint. `account_state` emits shape 2b
  with `reserved_cash: 0.0` / `reserved_shares: 0` (governor owns
  reservations, A2 b; module docstring says why); shares from us_equity
  positions only, int; money floats. `resolve_as_of` is A5 (a): open -> now
  UTC, closed -> last session close from /v2/calendar (7-day lookback,
  America/New_York close converted to UTC). `parse_rfc3339` truncates ns to
  us (fixtures trap 6) and is used everywhere. `requests` only, no
  alpaca-py, no caching, no config file I/O.
  Tests: `tests/test_data_layer.py` (offline, `requests.Session.get`
  monkeypatched, fixtures as bodies; 27 pass) and
  `tests/test_data_layer_live.py` (read-only, skipped unless
  GLASSBOX_LIVE=1; GETs only, never an order). `pytest.ini` adds
  `pythonpath = .` so `glassbox.*` imports from any cwd — this also makes
  conftest's `glassbox.screener` candidate resolvable once the screener
  lands. README gained a data-layer snippet. requirements.txt unchanged
  (nothing new needed). Screener suite unchanged: 4 pass, 12 xfail.
  Live smoke test NOT run this session (no .env on this box); run it once
  from a box with dev keys before trusting the live shapes.
- **Frozen:** `GB_INTERFACES.md`, `GB_INTERFACES.SIGNOFF-DRAFT.md`,
  `tests/test_screener_contract.py`, `tests/conftest.py`, everything under
  `tests/fixtures/` — all untouched. `glassbox/screener.py` path reserved
  for teakeycee, not created. Dev account untouched (no calls made).
- **Blocked:** teakeycee's signature on the draft (C1-C4 confirmation).
  The data layer is built to the draft + Jhoosier positions; if sign-off
  moves A2 or A5, `account_state` / `resolve_as_of` are the only two
  functions that change. Live run of `tests/test_data_layer_live.py`
  pending a box with the dev .env.
- **Attack next:** teakeycee: the screener can now be exercised against
  live snapshots via the data layer — `client = dl.AlpacaClient.from_env()`,
  `dl.get_contracts(client, "SPY", exp, exp)` then
  `dl.get_snapshots(client, "SPY", symbols=[...])` feed `screen_chain`
  directly with `as_of = dl.resolve_as_of(client)`. The `account_state`
  emitter for the governor is ready with reservations zeroed per A2 (b);
  the governor overlays its ledger-derived reservations on top. Please
  also run `GLASSBOX_LIVE=1 python -m pytest -q tests/test_data_layer_live.py`
  on the US box (read-only) and note the result in your block.

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
