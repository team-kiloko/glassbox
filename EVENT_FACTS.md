# EVENT_FACTS — GlassBox

> Verified facts about the hackathon. Each row is TAGGED by source; a build decision only
> binds on a `[primary]` ✅ row. Verified 2026-08-28 against the official lablab.ai event page
> (Jay clipped the page; SAGE cannot fetch lablab.ai directly — it 403s automated requests).
>
> **Refreshed 2026-09-02 by teakeycee** against **Alpaca's official event FAQ** (human
> export, read directly). That is a SECOND primary source, and it moved real build
> decisions — see the FAQ table and "What these facts changed in the build" below.
> Where the two primary sources differ in emphasis, both are kept and the build
> follows the conservative reading.

**Provenance:** `[primary]` official page (human-read) · `[secondary]` search/brief · `[ai-recalled]` unverified
**Status:** ✅ verified against primary · ⚠️ unverified · 🙋 NEEDS-YOU · ❌ found false

| Fact | Value | Source | Status |
|------|-------|--------|--------|
| Kickoff | Aug 29 2026, 00:00 JST (= Aug 28 15:00 UTC) — opening stream + Discord Q&A at 01:00 JST | `[primary]` schedule | ✅ |
| Submission deadline | Sep 5 2026, 00:00 JST (= Sep 4 15:00 UTC) — "End of Submissions" | `[primary]` schedule | ✅ |
| Format | Online, 7 days | `[primary]` | ✅ |
| Prize pool | $6,000: 🥇$2,500 · 🥈$1,500 · 🥉$1,000; each of 2 winning teams also gets $500 + Algo Trader Plus subs (per member). Paid to individuals; W-9/W-8BEN required. | `[primary]` | ✅ |
| Team size | 1–6 people | `[primary]` | ✅ |
| Core req — autonomous agent | Must build an autonomous AI trading agent using Alpaca's Trading API | `[primary]` | ✅ |
| Core req — MCP or CLI | Must use Alpaca's MCP server **or** its CLI | `[primary]` | ✅ |
| **Options mandatory?** | **YES** — "all strategies must incorporate options trading" | `[primary]` | ✅ |
| Judging account | Final submission needs a **brand-new, dedicated** Alpaca paper account. Reused accounts are **ineligible**. | `[primary]` | ✅ |
| Starting balance | Competition account **must be set to $100,000** | `[primary]` | ✅ |
| One-page write-up | Required: covers **AI logic, risk gates, Alpaca infrastructure** | `[primary]` | ✅ |
| **Judging criteria** | **P&L Performance** · Technology Implementation · Creativity & Originality · Presentation & Execution. Plus **Social engagement** (up to 5 X/LinkedIn posts). No public weights. **AMENDED — see the FAQ table below:** judged on P&L **plus creativity, autonomy, and robustness of the workflow**; P&L is important but **not alone**. | `[primary]` | ✅ |
| Deliverables | Title, short/long desc, tags · cover image · **video presentation** · **slide deck** · **public GitHub repo** · demo app platform + **Application URL** · **Alpaca paper account ID** (for P&L eval) | `[primary]` | ✅ |
| ↳ **UI / hosting** | **NO UI is required.** Hosting is needed **only if a demo app is submitted.** Two primary sources disagree in emphasis: the lablab form asks for a platform + Application URL, the Alpaca FAQ says no UI is required. **Read conservatively: a dashboard is OPTIONAL, not a gate.** | `[primary]` FAQ | ✅ |
| Repo public? | Public GitHub repo required **at submission**. (Private during build is fine.) | `[primary]` | ✅ |
| License | Submissions must be **original and MIT-compliant** | `[primary]` | ✅ |
| Paper environment | Simulated funds + real market data; free, no card | `[primary]` | ✅ |
| Video length | NOT specified on the event page — check the lablab Rule Book (lablab.ai/hackathon-rules) | — | 🙋 |
| Registration | Must enroll on lablab.ai + join the lablab Discord | `[primary]` | ✅ |
| Options data on free paper tier | Full SPY chain serves on FREE paper: contracts (strikes/expiries/OI), two-sided quotes w/ sizes, greeks+IV near-the-money. Greeks null on deep-ITM/illiquid; contracts paginate nearest-expiry-first. | `[primary]` live test 2026-08-30 | ✅ |

---

## Alpaca official FAQ — `[primary]`, verified 2026-09-02 by teakeycee

> Source: Alpaca's official event FAQ, human export held by teakeycee, read
> 2026-09-02. Same binding force as the event-page rows above. Where the two
> primary sources differ in emphasis, both are recorded and the **conservative**
> reading is the one the build follows — noted per row.

| Fact | Value | Source | Status |
|------|-------|--------|--------|
| **Scoring basis** | **TOTAL ACCOUNT EQUITY, not cash.** Open positions count at their mark. | `[primary]` FAQ | ✅ |
| **Official trading window** | **Mon Aug 31 09:30 ET → Fri Sep 4 09:30 ET** | `[primary]` FAQ | ✅ |
| **When equity is read** | **EOD Thursday Sep 3**, with **Sep 3 option exercises / assignments reflected**. The FAQ also mentions a **Friday 09:30 snapshot**. The two readings differ by one overnight. **We plan to the conservative one: Thursday EOD is binding.** | `[primary]` FAQ | ✅ |
| **Expected start** | The agent **should have begun trading the competition account Mon Aug 31 09:30 ET**. **We are starting late.** The FAQ does not make a late start disqualifying — it costs scored days, nothing more. | `[primary]` FAQ | ✅ |
| **Judged on** | **P&L plus creativity, autonomy, and robustness of the workflow.** P&L is important but **not alone**. | `[primary]` FAQ | ✅ |
| **UI required?** | **No.** Hosting is needed **only if a demo app is submitted.** | `[primary]` FAQ | ✅ |
| **Repo private during event?** | **Yes, permitted.** (Public is still required *at submission* — event-page row above.) | `[primary]` FAQ | ✅ |
| **MCP / CLI / SDK** | **MCP or CLI is sanctioned. An SDK is ALLOWED if the reasons are clearly explained and official SDKs are prioritized.** | `[primary]` FAQ | ✅ |
| **Options data feed** | **The free indicative feed is permitted.** **Latest quotes are real-time.** **Rely on the API, not the dashboard.** | `[primary]` FAQ | ✅ |
| **Strategy restrictions** | **None.** (GlassBox's defined-risk-only scope is OUR constraint, not the event's — see CLAUDE.md.) | `[primary]` FAQ | ✅ |
| **MCP order support** | **Single-leg AND multi-leg option orders are supported.** | `[primary]` FAQ | ✅ |
| **Pre-event work** | **Permitted, but MUST be disclosed in the README.** | `[primary]` FAQ | ✅ |
| **Backtests / simulated shocks** | **May be included as guardrail evidence.** | `[primary]` FAQ | ✅ |

### What these facts changed in the build

1. **Equity, not cash, is the score — and it is read at Thursday EOD.** A short
   premium position still open on Friday is scored at its **mark**, not at the
   premium collected: unrealised, and moving. Positions that **resolve on or
   before Sep 3** convert premium into scored equity instead of leaving
   mark-to-market residue in the number the judges read. This is why
   `max_expiry_date = 2026-09-03` is **DECIDED** (not PROPOSED) in the governor
   thresholds, and why the screener and governor reject any leg expiring after
   it. It is a scored-run bound, not a trading judgement.
2. **The dashboard became OPTIONAL.** No UI is required and hosting only matters
   if a demo app is submitted. Ranking it behind the strategist and the video is
   now supported by a primary source rather than by argument.
3. **The official SDK is a sanctioned execution path.** `alpaca-py` is already
   pinned; the reasoning the FAQ asks for is written up in
   `docs/EXECUTION_RATIONALE.md`, and MCP stays in the strategist / NL path.
4. **Autonomy is explicitly judged.** The scored run is **autopilot** with the
   governor as the sole gate — not approve-mode with a human clicking.
5. **Pre-event work is disclosed** in the README, as the FAQ requires.


## Still to read (not on the main event page)
- Exact **video length** limit → lablab Rule Book (`lablab.ai/hackathon-rules`).
- Any partner-prize tech (Technology Partners listed "before kickoff").

## Strategic note (moved the plan)
> **P&L Performance is an explicit judging criterion** and the paper account ID is required so judges
> can evaluate actual returns. The earlier assumption (from the research note) that "judges can't
> reward returns in a week" is **false per the primary source.** GlassBox's design still holds — but
> the agent must actually TRADE and post P&L on the fresh $100k account across the week, not only be
> auditable. Defined-risk options (premium-collecting spreads / iron condors) suit steady, non-blow-up
> P&L — but the agent needs to be placing paper trades EARLY, not just at the D6 demo run.
