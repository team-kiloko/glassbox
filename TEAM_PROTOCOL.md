# TEAM_PROTOCOL — GlassBox

How two humans in different timezones, each with an AI pod, build one system that
looks like it was built by a single mind. The contracts are the mind.

## Roles
- **Humans are the governors.** Only humans merge, decide, and commit. AIs propose;
  no AI output becomes project state until a human moves it across.
- **AI pods never talk directly.** TKC's pod and yours pass everything through repo
  artifacts (fixtures, contracts, HANDOFF notes). There is NO channel where one
  side's AI can trigger action on the other side.

## The seam is a contract, not a conversation
- `GB_INTERFACES.md` defines every data shape crossing between pods.
- A field changes there FIRST, by human agreement, before code depends on it.

## Contract tests are the neutral arbiter
- Code merges when its contract suite passes — regardless of which AI wrote it.
- This removes the whole "my AI vs your AI" category of dispute; fixtures don't care
  about authorship.
- Cross-pod adversarial fixtures are encouraged and asymmetric: each pod attacks the
  other's modules with fixtures; fixes stay with the owning pod.

## The baton is written
- One `HANDOFF.md` at the repo root, prepended per session:
  changed / frozen / blocked / attack-next. Read it before any work.

## Facts carry provenance
- Any claim about rules, judging, or platform behaviour is tagged
  (primary / secondary / AI-recalled) and human-verified against the PRIMARY source
  before it binds. Verified items live in `EVENT_FACTS.md` so neither pod re-litigates them.

## Cadence
- One synchronous human touchpoint per day, max, at the timezone overlap — decisions only.
  Everything else is async, through the repo.
- **Feature freeze: Sep 2.** After freeze, both pods switch from building to
  adversarial testing + pitch polish.

## Hygiene
- Fresh paper account, own keys, `.env` on-box only (`.env.example` placeholders in the repo),
  secrets scan before the repo goes public, MIT license, 2FA on both accounts.

## Ceremony budget
- If any of this visibly slows Day 1–2 velocity, cut weight **deliberately** — not silently.
