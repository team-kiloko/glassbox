# GB_INTERFACES.md — the seam

> The ONE place every data shape that crosses between the two pods is defined.
> **RULE:** a field changes HERE FIRST, by human agreement, before any code depends on it.
> Each pod builds in its own isolated context; this file is the only thing they share.
> Everything below is DRAFT until both humans sign off (see Change log).

## Module ownership (who builds what)

| Module | Owner |
|--------|-------|
| Chain screener | Tiki + Claude (relay) |
| Governor + contract suites | Tiki + Claude |
| Provenance ledger | Tiki + Claude |
| Telegram digest, report / dashboard generation | Tiki + Claude |
| MCP integration (Alpaca) | TKC + pod |
| LLM backend layer | TKC + pod |
| NL intent UX | TKC + pod |
| Dashboard front-end polish, video + deck | TKC + pod |

## The pipeline, and the shapes that cross the seam

Flow: **NL intent → strategy proposal → governor verdict → order + fill → ledger entry.**
Field names/types below are PLACEHOLDERS to agree on — pin the real ones here.

### 1. NL intent  (UX pod → Strategist)
```json
{ "intent_text": "NVDA flat for two weeks",
  "ticker": "NVDA", "horizon_days": 14,
  "view": "flat | up | down | volatile" }
```

### 2. Strategy proposal  (Strategist → Governor)
```json
{ "structure": "vertical_spread | iron_condor | ...",
  "legs": [ { "action": "buy|sell", "option_type": "call|put",
              "strike": 0, "expiry": "YYYY-MM-DD", "qty": 1 } ],
  "rationale": "plain-English why",
  "max_loss": 0, "max_gain": 0 }
```

### 3. Governor verdict  (Governor → Executor / Ledger)
```json
{ "approved": true,
  "checks": [ { "rule": "max_loss_cap", "passed": true, "detail": "..." } ],
  "reason": "plain-English verdict" }
```
The governor is the ONLY component that may emit an order. No naked short option is expressible.

### 4. Order + fill  (Executor via Alpaca MCP → Ledger)
```json
{ "order_id": "...", "status": "filled | rejected | ...",
  "legs": [ ... ], "submitted_at": "iso-utc", "fill": { } }
```

### 5. Ledger entry  (the audit record; consumed by the dashboard)
```json
{ "id": "...", "snapshot": { }, "proposal": { }, "verdict": { },
  "order": { }, "fill": { }, "ts": "iso-utc" }
```

## Change log
- 2026-08-28 — file created; all shapes DRAFT, pending both humans' sign-off.
