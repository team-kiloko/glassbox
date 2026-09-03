# SUBMISSION.md - GlassBox final submission checklist

> Everything the lablab.ai submission form requires, tracked from day 1 so
> nothing is discovered at the deadline. Owner fills status as items land.
> Deadline: Sep 4, 10:00 AM CDT (15:00 UTC). Submit with margin: target Sep 3.
> Sources: enrolled event page [primary] + lablab guidelines article.

| # | Item | Requirement | Status | Notes |
|---|------|-------------|--------|-------|
| 1 | Project title | Max 50 characters | DRAFT in docs/SUBMISSION_TEXT.md | 50 chars, at the limit, checked |
| 2 | Short description | Max 255 characters | DRAFT in docs/SUBMISSION_TEXT.md | 226 chars, checked |
| 3 | Long description | Min 100 words | DRAFT in docs/SUBMISSION_TEXT.md | ~240 words |
| 4 | Technology / category tags | Form picklist | DRAFT in docs/SUBMISSION_TEXT.md | Alpaca, MCP, options, Claude/agents, Streamlit |
| 5 | Cover image | 16:9, PNG/JPG | TODO | |
| 6 | Video presentation | Max 5 min, under 300MB | SCRIPT in docs/VIDEO_SCRIPT.md | Hero moment: the rejected root `20260902T150903Z-f6d2bb6ef6` replayed in the dashboard. Limit UNVERIFIED: lablab.ai/hackathon-rules 403s automated fetches; Jay confirms by hand. Record after the scored-session sample rebuild |
| 7 | Slide presentation | PDF | OUTLINE in docs/DECK_OUTLINE.md | 8 slides, one line each; Jay builds the PDF |
| 8 | Public GitHub repository | Public AT submission; MIT license | TODO | Flip only after secrets scan passes; LICENSE already in repo |
| 9 | Demo application platform | Streamlit / Replit / Vercel | **Streamlit** | Decided 2026-09-02 by Jhoosier. Streamlit Community Cloud deploys from the public repo; account created |
| 10 | Application URL | Live, judge-clickable | TODO | The audit dashboard on Streamlit Community Cloud. Needs the repo public (item 8) to deploy from it, so the URL lands on flip day; deploy from a private repo via Streamlit GitHub auth if we want it earlier |
| 11 | Alpaca paper account ID | The fresh competition account, $100,000 start, options Level 3 enabled at creation | **PA3424LCNZBS** | Created 2026-09-02 by Jhoosier on the bare team address. Keys in the vault (COMPETITION entry, separate from dev). Governor-pipeline orders only; no manual orders ever |
| 12 | One-page write-up | AI logic, risk gates, Alpaca infrastructure | DRAFT in docs/WRITEUP.md | Every number sourced from the repo; teakeycee to review the risk-gates section (HANDOFF 2026-09-03) |

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
