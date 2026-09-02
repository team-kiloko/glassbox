# Why execution goes through the official `alpaca-py` SDK

> Written 2026-09-02 by teakeycee, as executor lead. This document exists because
> **Alpaca's official FAQ asks for it**: MCP or the CLI is sanctioned, and an SDK
> is allowed **"if the reasons are clearly explained and official SDKs are
> prioritized."** (`EVENT_FACTS.md`, FAQ table, `[primary]` ✅.) These are the
> reasons.

## The short version

**MCP is in the loop, and it is in the right place.** GlassBox uses Alpaca's MCP
server in the **strategist / NL path** — the part of the system where a language
model reasons about the market and a human talks to it in English. That is what
MCP is for, and it is the requirement's target.

**Execution is not that part.** The step that turns an approved verdict into a
real position on a scored account is the one place in this system where
non-determinism is not a feature. It goes through **`alpaca-py`**, Alpaca's own
official Python SDK, already pinned at `alpaca-py==0.44.0`.

**Official SDKs are prioritized.** There is no third-party trading client
anywhere in this repo, and no hand-rolled HTTP order path. The only two things
that reach Alpaca are Alpaca's MCP server and Alpaca's SDK.

## The four reasons

### 1. Determinism, because the governor's guarantee ends where execution begins

Everything upstream of the executor is deterministic and replayable: the screener
has no clock, the governor has no I/O, the ledger has no wall clock, and
`replay_root` re-derives any recorded verdict from the entry's own inputs. That
chain of guarantees is the product.

An order path mediated by a language model breaks it at the last step. A tool
call is a *model's rendering* of an instruction; the SDK call is the instruction.
Between an approved verdict and a submitted order there must be nothing that can
paraphrase — no re-derived strike, no re-interpreted side, no helpfully rounded
limit. `abs(net_debit_credit)` on a single-leg order (seam 4a) is exactly the
kind of detail that survives a function call and does not reliably survive a
conversation.

### 2. Contract-testability, because a suite is the acceptance gate

CLAUDE.md: a module merges when its contract suite passes. GB-E holds the
executor to the seam's wire mapping — 4a's single-leg rule, 4b's
`position_intent`, `ratio_qty` and order-level `qty`, the `client_order_id`
scheme — and it does that by injecting a **`FakeTransport`** and asserting on the
exact request the executor built.

That is possible because the transport is one interface with two
implementations: `FakeTransport` for the suite, `AlpacaPyTransport` wrapping the
official `TradingClient` for real. The suite therefore proves the mapping without
a live market, a live account, or a live model — which is what lets the executor
be verified at 12:30 on a day the market opens at 13:30.

An MCP-mediated order path is testable only against a running server and a
model's willingness to call the same tool the same way twice. That is a fine
property for a strategist and a poor one for a gate.

### 3. Idempotency, on an account that is being scored

Seam shape 4 makes `client_order_id = <ORDER_ID_PREFIX> + <root ledger entry id>`
and requires the ledger entry to be written **before** submission so its id
exists to embed. The point is broker-side idempotency: a retried submission after
a timeout, a crash mid-submit, or an ambiguous network failure carries the **same**
`client_order_id`, and Alpaca refuses the duplicate rather than opening a second
position.

That property depends on the executor controlling the exact `client_order_id`
sent on every attempt, including retries. The SDK takes it as a field. Routing
that through a model is a way to lose the one string whose stability is the
difference between "did my order go through?" being answerable and being a manual
check on a scored account.

### 4. An injectable transport is the same argument the whole repo already makes

The data layer takes an injectable session so GB-D runs against recorded bodies
and no test touches the network. The screener takes its thresholds from its
caller so GB-S is deterministic. The ledger takes its path and its `ts` from its
caller so GB-L can write to a temp file and replay a fixture. The executor takes
an injectable transport for exactly the same reason, and it is the same reason
each time: **the seam is testable when the outside world is an argument.**

## What this does NOT mean

* **It is not a rejection of MCP.** MCP is used, in the strategist and NL path,
  and the FAQ confirms MCP supports both single- and multi-leg option orders — so
  this is a design choice about *where* determinism matters, not a workaround for
  a limitation.
* **It is not a third-party client.** `alpaca-py` is Alpaca's own SDK. The
  "prioritize official SDKs" instruction is satisfied literally: it is the only
  SDK in `requirements.txt`, pinned exactly, per CLAUDE.md's dependency rule.
* **It does not widen the blast radius.** The executor cannot express a naked
  short (structure-tagged constructors, seam 2e), cannot submit without an
  approved verdict, cannot reach a non-paper URL (the paper guard), and cannot
  invent a `client_order_id` prefix (it comes from `ORDER_ID_PREFIX` in `.env`,
  never from tracked code).

## Where each path is used

| Path | Component | Why |
|---|---|---|
| **Alpaca MCP server** | Strategist / NL intent | A model reasoning in English about a market, with tools. MCP's purpose. |
| **`alpaca-py` SDK** | Executor: order submission and status | Deterministic, contract-testable, idempotent, injectable. |
| **`requests` + injectable session** | Data layer reads | Read-only; recorded bodies drive GB-D with no network. |

