# Video script — GlassBox (target 4:30, hard stop 5:00)

**Length limit: 5 minutes, under 300 MB per SUBMISSION.md row 6, taken from the
lablab guidelines article. UNVERIFIED against lablab.ai/hackathon-rules — the
page returns 403 to automated fetches (EVENT_FACTS.md notes the same). Jay to
confirm by hand before recording.**

Recording setup: repo root, `streamlit run app/dashboard.py` open in a browser
at full width, sidebar showing `demo/ledger_competition_sample.jsonl`, a
terminal beside it. Record after teakeycee's scored session and the sample
rebuild land, so the numbers on screen are final; the two hero root ids below
are on the scored ledger already and do not change.

Ids used throughout:

| role | root id |
|---|---|
| rejected proof root | `20260902T150903Z-f6d2bb6ef6` |
| its approved twin | `20260902T150903Z-973c931c1d` |
| second approved root | `20260902T150958Z-fe8c507ed1` |
| second rejected root | `20260902T150958Z-b8f60bc82f` |

---

## 0:00–0:30 — Cold open: the refusal (dashboard, Hero tab)

**Screen:** Hero tab, pair `20260902T150903Z` selected. Right column red:
GOVERNOR REJECTED.

**Say:** "This is an autonomous options agent refusing its own trade. The
proposal said the most it could lose was two hundred and fifty dollars. The
governor did the arithmetic itself: a hundred and fifty-two thousand, against a
two-thousand-dollar cap. It refused on four checks and wrote down exactly how
wrong the claim was. GlassBox is agentic, but auditable, and this is what that
means."

**Click:** nothing yet. Hold on the four metrics.

## 0:30–1:10 — What it is (slide 1–2, then terminal)

**Screen:** slide 1 (title), slide 2 (pipeline).

**Say:** "Every cycle, GlassBox fetches the full SPY option chain from Alpaca's
paper tier, screens it fail-closed, builds defined-risk candidates, and hands
each one to a deterministic governor. The governor has no clock and no I/O. It
recomputes max loss from strikes, quantity and net price, and it reads the
strategist's claim only to record the divergence. It is the only component that
can emit an order. Everything it decides is written to an append-only ledger
before the order exists."

## 1:10–2:10 — The pair (dashboard, Hero tab)

**Screen:** Hero tab. Same pair.

**Say:** "Every run wrote two decisions under the same config hash, the same
clock, the same account state. Left: a five-wide SPY put vertical, one lot.
Claimed max loss four hundred and eleven, computed four hundred and eleven,
divergence zero, approved on all ten checks. Right: a deliberately oversized
cash-secured put. Same second, same thresholds, opposite answer."

**Click:** the pair selector. Pick `20260902T150958Z`.

**Say:** "Second run, fifty-five seconds later. The approved side is now four
lots, sized by asking the governor rather than computing a cap a second time.
The rejected side is refused again, on the same four checks, with the cap now
resolved against the account's live equity."

## 2:10–3:10 — Hero moment: replay (dashboard, Hero tab, then Chain tab)

**Screen:** Hero tab, pair `20260902T150903Z`, right column.

**Click:** "Replay this decision" under the rejected root.

**Say:** "Now the claim GlassBox makes: any decision can be re-derived from
nothing but its own record. This re-runs the governor on the entry's embedded
proposal, account state and clock, under the config file whose content hash the
entry names. Matched: true. If anyone edits the record or the thresholds, this
turns false."

**Click:** Chain tab. Select `20260902T150903Z-f6d2bb6ef6`.

**Say:** "Here are the ten checks. Seven are the seam's core vocabulary. Three
are extensions under the x prefix, and the dashboard renders them without
knowing their names. The failing ones are expanded: max loss cap, coverage,
cash floor, total open risk. Each carries the governor's own numbers."

**Click:** expand `max_loss_cap`. Hold two seconds.

## 3:10–3:50 — A real chain and a real fill (dashboard, Chain tab, Roots tab)

**Click:** Chain tab root selector, pick `20260902T150903Z-973c931c1d`.

**Say:** "The approved twin. Root written pre-submission, then a submitted
follow-up carrying the broker order id, then a fill at negative ninety cents
against an eighty-nine-cent limit. The client order id embeds the root id, so a
retry is refused by the broker as a duplicate."

**Click:** Roots tab.

**Say:** "One row per root, folded by root id. Status is the chain's latest,
never the root's own. Prompt version is null because no language model wrote
these proposals, and the ledger says so rather than leaving a gap."

## 3:50–4:20 — What cannot happen (slide 3–4)

**Screen:** slide 3 (defined-risk only), slide 4 (Alpaca infrastructure).

**Say:** "The order builder cannot express a naked short. The covering asset is
a required argument with no default. Execution goes through Alpaca's official
SDK with an account identity guard: it reads the account number over the
connection that would carry the order and refuses if it is not the one this run
was authorised for. Alpaca's MCP server sits in the natural-language strategist
path, where a model reasoning about the market belongs."

## 4:20–4:40 — Close (slide 5, then dashboard)

**Screen:** slide 5 (the numbers), then back to the Hero tab.

**Say:** "One hundred and eighty-nine contract tests, seven suites, one shared
seam signed by both humans. The competition account holds five lots of a governed put vertical,
every leg expiring inside the scored window, total computed max loss two
thousand and sixty-seven against a ten-thousand-dollar book cap. And one
refusal, replayable, on screen. GlassBox."

**End on:** Hero tab, rejected column, "matched = True" visible.

---

## Shot list (exact clicks, in order)

1. Hero tab, pair `20260902T150903Z-973c931c1d vs 20260902T150903Z-f6d2bb6ef6`. Hold.
2. Slides 1–2.
3. Hero tab, pair selector → `20260902T150958Z-fe8c507ed1 vs 20260902T150958Z-b8f60bc82f`.
4. Hero tab, pair selector → back to `20260902T150903Z`. Click **Replay this decision** (right column). Wait for the green "matched = True".
5. Chain tab → root `20260902T150903Z-f6d2bb6ef6` → expand `max_loss_cap`.
6. Chain tab → root `20260902T150903Z-973c931c1d`. Show timeline.
7. Roots tab. Hold.
8. Slides 3–5.
9. Hero tab, rejected column, replay result visible. End.

Numbers spoken on screen come from `demo/ledger_competition_sample.jsonl` at
commit `d557a69` and must be re-read if the sample is rebuilt after the scored
session.
