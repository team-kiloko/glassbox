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
