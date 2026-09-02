# GlassBox

A natural-language options strategist whose every action passes a deterministic
risk governor, with a replayable provenance ledger proving it. **Agentic, but auditable.**

Built for the lablab.ai × Alpaca "Options Alpha Agents" hackathon (Aug 28 – Sep 4 2026).
Paper trading only, on a dedicated Alpaca paper account.

## The pipeline
1. **NL intent in** — e.g. "NVDA flat for two weeks."
2. **Strategist proposes** a defined-risk options structure, in plain English, with a payoff view.
3. **Governor disposes** — deterministic, fail-closed. Computes max loss before any order; enforces
   position caps, cash floor, churn guard, leg-structure validation. The ONLY component that can
   place an order. No naked short options are expressible.
4. **Execution** — approve-button mode (a human clicks) or autopilot (governor is the sole gate).
   Order submission goes through Alpaca's official `alpaca-py` SDK; Alpaca's MCP server is used in
   the strategist / NL path. The FAQ asks for that choice to be explained, and it is, in
   `docs/EXECUTION_RATIONALE.md`.
5. **Provenance ledger** — every stage archived: snapshot, proposal, per-rule verdicts, order, fill.
   Rendered as a self-contained audit dashboard; the demo centerpiece is a trade the governor *rejected*.

## Pre-event work disclosure

Alpaca's official event FAQ permits pre-event work **provided it is disclosed
here**, so here it is, in full.

**Prepared before the Aug 28 kickoff:**
- The coordination spine and repo scaffolding: `TEAM_PROTOCOL.md`,
  `HANDOFF_PROTOCOL.md`, `HANDOFF.md`, `SETUP.md`, `SUBMISSION.md`, `LICENSE`,
  `.gitignore`, `.env.example`, and this README's outline.
- The project's premise and pitch — an NL options strategist behind a
  deterministic risk governor with a replayable provenance ledger.

**Written during the event, after kickoff:**
- **Every line of trading code.** `glassbox/screener.py`,
  `glassbox/governor.py`, `glassbox/ledger.py`, `glassbox/datafeed.py`,
  `glassbox/executor.py`, and everything under `scripts/`.
- **Every contract suite and every fixture** — GB-S, GB-C, GB-L, GB-D, GB-E —
  including all recorded Alpaca responses.
- `GB_INTERFACES.md` (the seam) in full, and its sign-off.
- All configuration and thresholds.

The git history is the evidence: it is complete, unsquashed, and every commit is
dated.

## How this repo is coordinated
Two humans, two AI pods, one system. See:
- `TEAM_PROTOCOL.md` — how we work (humans commit, AIs propose, pods never talk directly).
- `GB_INTERFACES.md` — the seam: every data shape crossing between pods.
- `HANDOFF.md` — the daily baton (read first, write last, each session).
- `EVENT_FACTS.md` — verified hackathon rules (event page + Alpaca's official FAQ).
- `docs/EXECUTION_RATIONALE.md` — why execution uses the official SDK and MCP sits in the NL path.

## Setup
1. Python 3.11+; create a virtualenv.
2. Copy `.env.example` to `.env` and fill in your Alpaca **paper** keys. Never commit `.env`.
3. (build steps land here as modules come online)

## License
MIT — see `LICENSE`.
