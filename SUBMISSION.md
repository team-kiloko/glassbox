# SUBMISSION.md - GlassBox final submission checklist

> Everything the lablab.ai submission form requires, tracked from day 1 so
> nothing is discovered at the deadline. Owner fills status as items land.
> Deadline: Sep 4, 10:00 AM CDT (15:00 UTC). Submit with margin: target Sep 3.
> Sources: enrolled event page [primary] + lablab guidelines article.

| # | Item | Requirement | Status | Notes |
|---|------|-------------|--------|-------|
| 1 | Project title | Max 50 characters | TODO | Working name: GlassBox |
| 2 | Short description | Max 255 characters | TODO | One-line pitch: agentic but auditable |
| 3 | Long description | Min 100 words | TODO | Pipeline + governor + provenance story |
| 4 | Technology / category tags | Form picklist | TODO | Alpaca, MCP, options, Claude/agents |
| 5 | Cover image | 16:9, PNG/JPG | TODO | |
| 6 | Video presentation | Max 5 min, under 300MB | TODO | Hero moment: a governor REJECTION replayed in the dashboard. Verify limits at lablab.ai/ai-articles/hackathon-guidelines |
| 7 | Slide presentation | PDF | TODO | |
| 8 | Public GitHub repository | Public AT submission; MIT license | TODO | Flip only after secrets scan passes; LICENSE already in repo |
| 9 | Demo application platform | Streamlit / Replit / Vercel | TODO | Jhoosier picks at seam sign-off |
| 10 | Application URL | Live, judge-clickable | TODO | The audit dashboard |
| 11 | Alpaca paper account ID | The fresh competition account, $100,000 start, options Level 3 enabled at creation | TODO | Created ~Sep 1 (Monday if suite passes). Reused accounts INELIGIBLE. ID goes here and in HANDOFF when created |
| 12 | One-page write-up | AI logic, risk gates, Alpaca infrastructure | TODO | The governor section writes itself from the contracts |

Team decisions of record: social engagement track NOT pursued (no post links
will be submitted); Featherless NOT used (partner prizes forgone, main track
unaffected).

Pre-flip checklist for item 8, run in order on submission day:
1. Secrets scan over full history (keys, seeds, passwords, vault contents).
2. Confirm .env absent from history; .env.example placeholders only.
3. Confirm dev/competition account IDs present are intentional (IDs are
   required disclosures, not secrets).
4. Flip repo public; verify LICENSE renders; verify README quickstart works
   for a stranger.
