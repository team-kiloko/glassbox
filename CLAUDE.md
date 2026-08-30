# CLAUDE.md - GlassBox (team-kiloko) - Claude Code operating notes

You are the builder half of teakeycee's relay: this chat writes code against
contracts; a separate planning chat designs and reviews. Jhoosier (Japan) and
his agent pod build in this same repo on the opposite schedule. Coordination
rules live in HANDOFF_PROTOCOL.md and are binding.

## Session start, always
1. Read HANDOFF.md top block(s) before touching anything. Frozen means frozen.
2. Read SETUP.md if environment work is involved; GB_INTERFACES.md before any
   code that crosses module boundaries.
3. Respect CURRENT LEADS: only modify modules teakeycee currently leads unless
   the newest HANDOFF block hands one over or requests the work (Attack next).

## Build rules
- Contract tests are the acceptance gate: a module merges when its suite
  passes. Write or extend the suite with the code, not after.
- Direct generation, whole files. Never patch indented Python via string
  matching or sed.
- Dependencies: pin exact versions in requirements.txt the moment one is added.
- Thresholds and tunables go in config, never hardcoded. Mark PROPOSED until
  calibrated.
- Every order built anywhere in this codebase carries client_order_id prefix
  from ORDER_ID_PREFIX (this box: tkc-).
- Governor scope is settled: defined-risk only (covered calls, cash-secured
  puts, defined-risk verticals; iron condors only as two verticals). The order
  builder must be unable to express a naked short option. The governor
  computes max loss independently; it never trusts a strategist-supplied
  figure.
- Paper trading only. Trading base URL must contain "paper". If code or
  config ever points elsewhere, stop and raise it.

## Secrets and safety
- Secrets live only in .env (mode 600, gitignored). Never read them into
  output, never commit them, never write them into any file that is tracked.
- .env.example carries placeholders only. Env names: ALPACA_API_KEY,
  ALPACA_SECRET_KEY (ALPACA_API_SECRET is retired).
- No manual or ad-hoc orders against any account from this session unless
  teakeycee explicitly asks; the dev account is shared with Jhoosier's pod
  and is left flat (or documented in HANDOFF) at session end.
- git status before every commit; .env or key-like strings staged = full stop.

## Current state pointers
- EVENT_FACTS.md: verified hackathon rules (options mandatory; P&L is judged;
  submission needs the competition account ID; freeze Sep 2; submit Sep 4).
- SUBMISSION.md: deliverables checklist.
- Free paper tier serves the full options chain (proven): contracts endpoint
  paginates nearest-expiry-first (filter expiration_date_gte/lte); greeks can
  be null on deep-ITM/illiquid strikes; snapshots use feed=indicative. The
  screener must fail closed on null greeks, never guess.

## Session end, always
Help compose the HANDOFF.md CLOSE block (Changed / Frozen / Blocked / Attack
next), prepend it, and remind teakeycee to commit and push it. A block that
is not pushed does not exist.
