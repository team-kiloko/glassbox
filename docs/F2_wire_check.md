# F2 wire-format check - net_debit_credit vs Alpaca mleg (2026-09-02, Jhoosier pod)

Checked against Alpaca docs, not inferred. Result: the draft's sign convention
matches the wire. Units are per-share. Two corrections to the reconciliation
rule fall out of the check.

## Verified

1. **Sign.** alpaca-py `LimitOrderRequest.limit_price`: "For the mleg order
   class, this is specified such that a positive value indicates a debit
   (representing a cost or payment to be made) while a negative value
   signifies a credit (reflecting an amount to be received)." Same statement
   on the learn page: "credits are displayed as negative values, while debits
   are shown as positive values." Draft §2c (positive = debit) is a 1:1 match.
   A6 stands.
2. **Units.** Level 3 guide: "Net Price (per contract) x 100 = 5 x 100 = $500"
   and cost basis = margin + (Net Price x Option Multiplier). The mleg
   limit_price is the per-share net for ONE unit of the spread; the 100x
   multiplier and the parent qty are applied downstream. Dashboard example
   shows a debit spread at limit 2.58, i.e. per-share. teakeycee's F2
   position (per-share, multiplier explicit in governor math) is correct.
3. **Legs on the wire** carry `symbol`, `side` (buy|sell), `ratio_qty`
   (integers in simplest form, GCD 1), `position_intent`
   (buy_to_open|sell_to_open|buy_to_close|sell_to_close). The parent order
   carries `qty`, `type: limit`, `limit_price`, `order_class: mleg`,
   `time_in_force: day`. 2 to 4 legs.

## Corrections to the draft (propose at sign-off)

C1. **Reconciliation rule must not multiply by proposal qty.** The wire
    limit_price is per unit of spread, independent of qty. Restate:
    `net_debit_credit = sum over legs of sign(action) * limit_price * ratio_qty`,
    per share, buys positive, sells negative. Total dollars =
    net_debit_credit * 100 * qty, computed by the governor, never carried in
    the proposal.

C2. **Move qty to the proposal level; legs carry `ratio_qty`.** Mirrors the
    wire exactly, removes the ambiguity of per-leg qty vs order qty, and the
    GCD=1 rule becomes a governor structure_valid check. Every structure in
    scope has ratio 1:1 anyway.

C3. **Single-leg structures are NOT mleg.** mleg requires 2+ legs. A covered
    call and a cash-secured put are plain single-leg option orders: the wire
    limit_price is always positive and direction comes from `side`. So the
    seam's signed net (CSP = negative credit) maps to wire as
    `limit_price = abs(net)`, `side = sell`. Not zero translation, but one
    line, and it belongs in the executor's structure-tagged constructors.
    Record it so nobody submits a negative limit on a single-leg order.

C4. **Add `position_intent` to the order shape (§4)** or derive it in the
    executor from action + whether the account already holds the contract.
    Opening-only for this hackathon: buy -> buy_to_open, sell -> sell_to_open.
    Closing trades (if we ever exit early) need the _to_close intents.

## Sources
- https://alpaca.markets/sdks/python/api_reference/trading/requests.html
- https://docs.alpaca.markets/docs/options-level-3-trading
- https://alpaca.markets/learn/how-to-trade-options-with-alpaca
