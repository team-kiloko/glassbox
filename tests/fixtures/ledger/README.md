# Provenance ledger golden entries (GB-L)

Hand-built, **synthetic** fixtures for the GlassBox provenance ledger, per
`GB_INTERFACES.md` shape 5 and 5a. No live capture is claimed and no account data
appears here.

The embedded proposals, account states, clocks and verdicts are the **governor's
own golden fixtures** (`../governor/`), so a ledger entry here is a real decision
made by the real governor against a hand-authored expectation — not a plausible
blob. GB-L-F05 cross-checks every embedded verdict against the GB-C golden's
`checks` map, which is where the circularity stops: the ledger fixtures cannot
drift from the governor's contract without a test going red.

## Files

| File | What it is |
|------|------------|
| `entries.jsonl` | the ledger itself — one JSON entry per line, append order |
| `expected_chains.json` | the golden fold by root id, plus the GB-C cross-reference |

## 18 entries, 6 chains

| Chain | Path | Ends | Point |
|-------|------|------|-------|
| A | root → submitted → partial_fill → filled | `filled` | the happy path |
| B | root only | `governor_rejected` | a rejection is **complete at the root** |
| C | root → submitted → broker_rejected → **correction** | `broker_rejected` | a correction appends |
| D | root → submitted → canceled | `canceled` | human-approved, pulled |
| E | root → submitted → expired | `expired` | `prompt_version` is **null** |
| F | root → submitted → partial_fill | `partial_fill` | **still in flight** |

## Traps these fixtures exist to catch

1. **Chains are not contiguous in the file.** C's correction, D's cancel and E's
   expiry all land after later chains opened. A fold that walks forward from a root
   until it hits another root gets C, D, E and F wrong. Fold by `root_id`, always.
2. **`partial_fill` is NON-TERMINAL.** Chain F ends on it and is still working;
   chain A passes through it on the way to `filled`. A reader with a
   terminal-only status vocabulary misfiles a live order as a finished one.
3. **A correction appends, it never edits.** `c004` carries `corrects: c003` and a
   different reject reason. **`c003` is still in the file, byte for byte.** The
   ledger is append-only: the wrong record stays, and the right one points at it.
   A ledger you can edit is a ledger you cannot trust.
4. **`null` is a statement, absence is a bug.** `order` and `fill` are `null` on
   every root and on entries that produced neither — **never key-omitted** (shape
   5). The same discipline is applied to `snapshot` / `proposal` / `verdict`, which
   are null on follow-ups, and to `prompt_version`, which is null on chain E
   because no LLM produced that proposal — not `""`, not `"none"`, not missing.
5. **`approved_by` / `approved_at` are null in autopilot.** Chain A ran on
   autopilot and records both as null, which is a fact about the run, not a gap.
   Chain B was in approve mode and *also* records null, because the governor
   refused and there was nothing for a human to confirm.
6. **A governor rejection is a complete audit record.** Chain B embeds the entire
   verdict — all eight checks with their details, including the
   `claim_divergence=619.00` that caught the false claim — even though no order was
   ever built. The rejections are the entries most worth keeping.

## `client_order_id` in these fixtures

Order payloads carry `client_order_id = <prefix><root entry id>` per shape 4.
The prefix rendered here is **`tkc-`, an EXAMPLE ONLY**, exactly as the seam
permits ("configuration, not constants"). **No tracked module hardcodes a
prefix** — `glassbox/ledger.py` reads `ORDER_ID_PREFIX` from the environment and
raises when it is unset, and GB-L-07 greps the package to prove it.

## Three things shape 5 leaves open, filled in here — PROPOSED

Written down because they are the ledger lead's choices, not the seam's, and both
humans have to agree before anything else depends on them:

1. **`approved_pending` as a root status.** 5a requires the root entry to be
   written **pre-submission**, but the status vocabulary has no value for
   "approved, not yet submitted" — its values all describe a rejection or a state
   an order is already in. The seam marks the vocabulary PROPOSED as to
   completeness and says adding a value is a seam change, so this is proposed,
   not taken.
2. **`corrects` as a nullable field on every entry.** The seam says a correction
   "references the id of the entry it corrects" but gives it no field, and
   `root_id` cannot carry it — that is the fold key. `corrects` is null on all 17
   other entries, present on all 18.
3. **`snapshot` composition.** Shape 5 leaves `snapshot` as an open object. Here
   it is `{account_state, clock}` — precisely what the replay helper needs to
   re-derive the verdict, which is what makes the provenance claim executable
   rather than decorative.

## Serialization is pinned by this file

`entries.jsonl` **is** the format specification: one entry per line, UTF-8, keys
in the shape-5 order (with `corrects` after `root_id`), nested objects
key-sorted, timestamps ISO-8601 UTC with a `Z`. GB-L-11 re-serializes every golden
entry through `glassbox.ledger` and requires the bytes back. Two writes of the
same entry are byte-identical, which is what lets a diff of this file mean
something.
