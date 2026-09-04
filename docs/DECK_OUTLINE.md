# Deck outline — GlassBox (8 slides, one line each)

Jay builds the PDF. One line of content per slide; the speaker text is in
`docs/VIDEO_SCRIPT.md`. Slides 1–2 play at 0:30, 3–4 at 3:50, 5 at 4:20; 6–8
are for the PDF deliverable only and do not appear in the video.

1. **GlassBox — agentic, but auditable.** An autonomous options agent whose every order passes a deterministic governor, with a ledger that replays any decision.
2. **The pipeline.** chain screen → candidates → governor verdict → order → ledger; `build_candidates` is the one-function seam where the MCP strategist plugs in.
3. **Defined-risk only.** The order builder cannot express a naked short: the covering asset is a required argument, and iron condors exist only as two governed verticals.
4. **Alpaca infrastructure.** Free paper tier for the chain, official `alpaca-py` SDK for execution with an account identity guard, MCP in the natural-language path, `paper` in the URL on every request.
5. **The numbers.** 189 contract tests across 7 suites; 5 lots of a governed 763/758 SPY put vertical; computed max loss 2,067 on a 10,000 book cap; one refusal on the ledger, replayable.
6. **Ten checks, every decision.** structure_valid · net_reconciles · max_loss_cap · coverage · cash_floor · churn_guard · market_open · x_position_cap · x_max_expiry · x_total_open_risk.
7. **The refusal.** Claimed 250.00 · computed 152,584.00 · cap 2,000.00 · divergence 152,334.00 — refused on four checks, written down, replayed matched=True.
8. **Two pods, one seam.** Japan and the United States, coordinated only through the repo; GB_INTERFACES.md signed by both humans; pre-event work disclosed in the README.

Cover image (SUBMISSION.md row 5) can be slide 7 rendered at 16:9.
