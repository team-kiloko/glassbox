# EVENT_FACTS — GlassBox

> Verified facts about the hackathon. Each row is TAGGED by source; a build decision only
> binds on a `[primary]` ✅ row. Verified 2026-08-28 against the official lablab.ai event page
> (Jay clipped the page; SAGE cannot fetch lablab.ai directly — it 403s automated requests).

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
| **Judging criteria** | **P&L Performance** · Technology Implementation · Creativity & Originality · Presentation & Execution. Plus **Social engagement** (up to 5 X/LinkedIn posts). No public weights. | `[primary]` | ✅ |
| Deliverables | Title, short/long desc, tags · cover image · **video presentation** · **slide deck** · **public GitHub repo** · demo app platform + **Application URL** · **Alpaca paper account ID** (for P&L eval) | `[primary]` | ✅ |
| Repo public? | Public GitHub repo required **at submission**. (Private during build is fine.) | `[primary]` | ✅ |
| License | Submissions must be **original and MIT-compliant** | `[primary]` | ✅ |
| Paper environment | Simulated funds + real market data; free, no card | `[primary]` | ✅ |
| Video length | NOT specified on the event page — check the lablab Rule Book (lablab.ai/hackathon-rules) | — | 🙋 |
| Registration | Must enroll on lablab.ai + join the lablab Discord | `[primary]` | ✅ |

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
