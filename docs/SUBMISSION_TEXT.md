# Submission form text — DRAFT (SUBMISSION.md rows 1–4)

Character and word counts are checked with `wc`; the limits are lablab's
(title ≤ 50 chars, short ≤ 255 chars, long ≥ 100 words).

## 1. Title (≤ 50 characters)

```
GlassBox: agentic options trading, fully auditable
```

50 characters (at the limit).

## 2. Short description (≤ 255 characters)

```
An autonomous options agent on Alpaca whose every order passes a deterministic, fail-closed risk governor. An append-only ledger replays any decision from its own inputs; the demo's centrepiece is a trade the governor refused.
```

226 characters.

## 3. Long description (≥ 100 words)

GlassBox is an autonomous options trading agent built for the Alpaca Options
Alpha hackathon, and its premise is that an agent should be auditable before it
is clever. Every cycle screens the full SPY option chain from Alpaca's paper
tier, builds defined-risk candidates, and hands them to a deterministic
governor that recomputes max loss from strikes, quantity and net price. It never
trusts the strategist's claim, reading it only to record how far off it was.
Ten checks run on every decision, including a 2% per-structure cap and a 10%
book cap on the scored account, a cash floor, a churn guard, and an expiry bound
so positions resolve inside the scored window. The order builder cannot express
a naked short option: the covering asset is a required argument. Every decision
is written to an append-only provenance ledger before any order exists, with
the account snapshot, the proposal, the per-rule verdict, the config content
hash and the code version. A Streamlit dashboard folds those chains, renders
every check, and replays any verdict from its own inputs. The hero exhibit is
the run where a deliberately oversized cash-secured put claiming a 250 max loss
was refused on the governor's own arithmetic: 152,584 against a 2,000 cap.
Execution uses Alpaca's official SDK with an account identity guard and
idempotent client order ids; Alpaca's MCP server sits in the natural-language
strategist path. Seven contract suites, 189 tests, are the merge gate.

About 240 words.

## 4. Tags

Alpaca · MCP · options · Claude / agents · Streamlit · Python · risk management
· provenance
