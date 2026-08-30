# SETUP.md - GlassBox environment setup and build start (for AI pods)

Audience: the AI systems assisting each human. This is the executable checklist
for getting from "repo with coordination docs" to "both sides building." Phases
1 and 3 run per side; phase 2 is Jhoosier's. Each phase ends with an explicit
DONE-WHEN condition; do not proceed past an unmet one without your human's
explicit override, noted in HANDOFF.md. The human-readable version is
docs/setup_plan.svg. Companion protocol: HANDOFF_PROTOCOL.md.

Ownership note: Jhoosier creates the team email and the dev Alpaca account.
The competition account (~Sep 1) is created fresh on the bare team address;
who executes that creation is confirmed at a touchpoint before Sep 1.

## Phase 1 - Coordination spine (BOTH, in repo)

1. Merge into the repo: HANDOFF_PROTOCOL.md (root), docs/handoff_protocol.svg,
   docs/setup_plan.svg, this file.
2. Update TEAM_PROTOCOL.md: add the current-lead-per-module rule and the
   twice-daily baton cadence; remove the fixed ownership framing.
3. Update GB_INTERFACES.md: relabel all parties to teakeycee / Jhoosier;
   replace the ownership table with a CURRENT LEAD table (initial leads set at
   the phase 4 sign-off); shapes remain DRAFT until both humans sign.
4. Refresh EVENT_FACTS.md from the enrolled event page (primary source):
   five judging criteria (P&L, technology, creativity, presentation, social);
   dev-vs-fresh-competition account rule; submission requires the competition
   paper account ID only; $100,000 starting balance; one-page write-up (AI
   logic, risk gates, Alpaca infrastructure); MIT compliance; prize terms.
   Team decisions to record: social engagement track NOT pursued; Featherless
   NOT used.
5. Add LICENSE (MIT) at repo root; README already references it.
6. Create SUBMISSION.md: title (max 50 chars), short description (max 255
   chars), long description (min 100 words), tech and category tags, cover
   image 16:9 PNG/JPG, video max 5 min under 300MB, slide deck PDF, public
   repo URL, demo platform + URL, competition account ID, one-page write-up.
7. Repo visibility: private during the build; flip public only after the
   pre-submission secrets scan passes.

DONE-WHEN: all six files present on main; EVENT_FACTS has no unverified item
that gates a build decision.

## Phase 2 - Team email + dev Alpaca account (JHOOSIER)

1. Create the team Gmail: fresh account, his recovery info, 2-Step
   Verification on, credentials into the shared vault.
2. Sign up at app.alpaca.markets/signup using the plus-address
   `<team>+dev@gmail.com`. The bare `<team>@gmail.com` is RESERVED for the
   competition account signup (~Sep 1); do not use it now.
3. MFA enrollment: when the QR appears, reveal the text setup key and store it
   in the vault BEFORE completing enrollment, then enroll in his authenticator.
   (The seed is only visible at enrollment; capturing it lets teakeycee add
   the same seed later with no reset.)
4. Paper only: do not begin any live-account application; no identity
   verification is needed or wanted.
5. Generate paper API keys; store key + secret in the vault entry. Secrets
   never appear in chat, the repo, or HANDOFF.md.
6. Smoke test from his box: GET https://paper-api.alpaca.markets/v2/account
   with APCA-API-KEY-ID and APCA-API-SECRET-KEY headers; expect a JSON
   account object.
7. HANDOFF CLOSE block: dev account created, its account ID, "credentials in
   the shared vault," client_order_id prefixes in force (tkc- / jho-), account
   left flat.

DONE-WHEN: teakeycee can read the vault entry and his own smoke test against
the dev account succeeds from his box.

## Phase 3 - Local environments (BOTH, parallel, per side)

1. Clone the repo; create a Python 3.11+ virtualenv.
2. Copy .env.example to .env; fill dev account keys from the vault. .env is
   gitignored; verify before first commit.
3. requirements.txt: pin every dependency to an exact version (alpaca-py
   included) the moment it is first installed.
4. Install alpaca-py; the side currently hosting the running agent also
   configures Alpaca's official MCP server against the dev account keys.
5. Verification gate, in order:
   a. Account read succeeds (as phase 2 step 6).
   b. Equity market data fetch succeeds (bars for a liquid ETF).
   c. OPTIONS CHAIN fetch succeeds for a liquid underlying, including quotes
      and expirations. This is the critical unknown from prior experience
      (options data access tiers); prove it on the free paper tier BEFORE any
      strategy code exists. If it fails, that is a build-shaping fact: record
      it in EVENT_FACTS immediately and raise it at the next touchpoint.
6. LLM topology: teakeycee's relay runs on his separate API Console account
   with a spend budget set for the event; Jhoosier's pod runs on his own
   account. The runtime strategist bills to whoever hosts the agent that day;
   both sides track cost as a first-class number.

DONE-WHEN: both sides report a, b, c green in a HANDOFF block.

## Phase 4 - Seam sign-off, then first build (BOTH)

1. Synchronous touchpoint (the day's one sync): sign off GB_INTERFACES shapes,
   set initial CURRENT LEADS, Jhoosier picks the demo platform (Streamlit /
   Replit / Vercel), confirm who creates the competition account ~Sep 1.
2. Shape amendments to carry into sign-off: proposal includes net debit or
   credit and per-leg limit prices (the governor must compute max loss
   independently, never trust the strategist's own figure); verdict and
   ledger entries carry config version and prompt version; mode
   (approve / autopilot) appears in the verdict-to-order path.
3. Governor scope (decided): defined-risk structures only. Covered calls,
   cash-secured puts, defined-risk verticals; iron condors only as the
   composition of two verticals. Naked short options are structurally
   inexpressible in the order builder. Thresholds (universe, DTE bounds,
   caps, cash floor) live in config, marked PROPOSED until calibrated.
4. Suggested opening split (leads rotate freely after): one side takes data
   layer + chain screener with golden fixtures; the other takes MCP wiring +
   NL intent path. Governor contracts (GB-C series) drafted next; the
   governor is the highest-value module and gets the deepest suite,
   including a fixture where the strategist claims a false max_loss.
5. Every module merges only when its contract suite passes; authorship is
   irrelevant to acceptance.

DONE-WHEN: shapes signed, leads declared in HANDOFF, first two modules in
progress on separate leads.

## Standing constraints (all phases)

- No secrets in the repo, chat, or HANDOFF; vault pointers only.
- No AI-to-AI channel; artifacts through the repo, humans carry the baton.
- Event-rule claims bind only via EVENT_FACTS with a human-verified primary
  source.
- Dev account may be messy but is left flat (or documented) at every CLOSE.
- The competition account does not exist yet; nothing references it except
  the ~Sep 1 milestone. When created: brand-new signup, $100,000 starting
  balance, account ID into HANDOFF and SUBMISSION.md, keys via vault,
  governor-pipeline orders only, no manual orders ever.
