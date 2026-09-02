# `demo/ledger_sample.jsonl` — the demo's hero artefact

A real provenance ledger, written by a real run of the real pipeline against the
DEV paper account. Not a mock, not a fixture: every entry in it was produced by
`scripts/dry_run.py` driving the live chain through the screener, the governor,
and the ledger writer, and the order entries were produced by the executor
talking to Alpaca.

It is committed **so the dashboard has something to render before the scored run
exists**, and so the video has something to show that is true.

## What is in it

One JSONL entry per line, GB_INTERFACES.md **shape 5**. Two kinds:

* **Root entries** (`root_id: null`) — the decision. They carry `snapshot`,
  `proposal` and `verdict`, and their `order` / `fill` are `null` because a root
  is written **before** submission (5a). Its `id` is what the order's
  `client_order_id` embeds.
* **Follow-ups** (`root_id` set) — one per transition: `submitted`, then
  `filled` / `partial_fill` / `broker_rejected` / `canceled` / `expired`.

## How to read it (this is the dashboard's whole job)

```python
from glassbox.ledger import load, list_roots, fold_chain, current_status

entries = load("demo/ledger_sample.jsonl")
for root in list_roots(entries):
    chain = fold_chain(entries, root["id"])
    status, terminal = current_status(entries, root["id"])
```

Two traps, both of which the ledger's own helpers avoid for you:

1. **Fold by `root_id`, never by adjacency.** In any real run the entries of
   different chains interleave. Walking forward from a root until you meet the
   next root gets most of them wrong.
2. **`partial_fill` is NOT terminal.** A chain sitting on one may still reach
   `filled`, `expired` or `canceled`.

## The rejected entry is the point

A governor rejection is a complete, terminal chain of exactly one entry, with
every `checks[]` rule and the numbers the decision turned on in its `detail`.
That is the entry worth putting on screen: it shows the system refusing a trade,
and shows precisely why, in the governor's own arithmetic rather than in the
strategist's claim.

## And it replays

```python
from glassbox.ledger import replay_root
replay_root(root, thresholds, config_version=root["config_version"])   # matched: True
```

Every root re-derives its recorded verdict from its **own** embedded proposal,
account state and clock, under the config it names. Nothing else is consulted.
That is the claim GlassBox makes, and it is executable rather than asserted.

## Scrubbing

Entries are written to `data/ledger_dev.jsonl` (gitignored) and mirrored here
after a scrub pass that drops account-identifying keys and refuses to write if a
credential appears anywhere in the entry. A shape 5 entry carries balances and
share counts, not account identity, so the scrub normally removes nothing — and
the run prints how many fields it removed, so "scrubbed" is a measured fact
rather than a promise.
