# Alpaca reference links — GlassBox

> One shared reference for both pods. All docs verified reachable 2026-08-28.
> Save at `docs/alpaca-links.md` in the repo.

## Start here
- **Trading API** (our primary interface) — https://docs.alpaca.markets/docs/getting-started-with-trading-api
- **Market Data** — https://docs.alpaca.markets/docs/getting-started-with-alpaca-market-data

## Required tool (must use one — hackathon core requirement)
- **MCP Server** — https://docs.alpaca.markets/us/docs/alpaca-mcp-server
- **CLI** — https://docs.alpaca.markets/us/docs/alpacas-cli
  *(CLI is lighter for long-running agent/cron sessions; MCP is the "AI assistant talks to Alpaca" path. GlassBox's brief leans MCP for execution.)*

## Options — the core of GlassBox
- **Options Trading Overview** — https://docs.alpaca.markets/us/docs/options-trading-overview
- **Options Orders** (valid order payload examples) — https://docs.alpaca.markets/us/docs/options-orders
- **Multi-leg / Options Level 3** (spreads, iron condors — our defined-risk structures) — https://docs.alpaca.markets/us/docs/options-level-3-trading
- **Option Chain API** (quotes + **greeks** — feeds the risk/payoff view and the governor's max-loss math) — https://docs.alpaca.markets/us/reference/optionchain
- **Option Contracts API** — https://docs.alpaca.markets/us/reference/get-options-contracts
- **Real-time Option Data** — https://docs.alpaca.markets/us/docs/real-time-option-data

## Also
- **Python SDK (alpaca-py)** — https://docs.alpaca.markets/us/docs/sdks-and-tools
- **Paper Trading** — https://docs.alpaca.markets/us/docs/paper-trading
- **Streaming market data (WebSocket)** — https://docs.alpaca.markets/us/docs/streaming-market-data

## ⚠️ Setup flag
The multi-leg structures GlassBox is built on (spreads, iron condors) require **options Level 3**
enabled on the trading account. Turn it on when you create the fresh, dedicated **$100,000** paper
account for judging — otherwise the governor's spread/condor legs will be rejected at submission time.
