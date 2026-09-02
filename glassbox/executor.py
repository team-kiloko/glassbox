"""Executor — GB_INTERFACES.md shape 4, 4a, 4b, and 5a's follow-up chain.

The component that turns an approved verdict into a real order. Everything
upstream of here has been arguing about whether a trade is safe; this is the
part that does it, and it is the last code that runs before money moves.

It is deliberately the least clever module in the system. It has no opinion
about risk — the governor owns that — and exactly one opinion about approval: if
the verdict says no, nothing leaves. What it owns is the mapping from the seam
to the wire, and that mapping is where a silent error costs a real position.

**A naked short option is not expressible here.** Not "is rejected" — not
representable. The seam is explicit (2e) that this invariant cannot live in the
schema: a covered call IS a lone short call leg, and only account state
distinguishes it from a naked one. So it lives in this API instead. The two
single-leg builders take the covering asset as a **required argument with no
default** — omitting it is a `TypeError`, not a validation message — and there
is no general-purpose single-leg builder in the module for a hurried caller to
reach for at 2am on submission day. :data:`STRUCTURE_BUILDERS` is the whole
dispatch surface and it covers exactly the closed enum.

Three wire details the seam pins and this module is the only place that applies:

1. **4a — single-leg structures are NOT `mleg`.** `mleg` requires two or more
   legs, so only a vertical is one. On a single-leg order the wire
   `limit_price` is **always positive** and the direction comes from `side`:
   ``limit_price = abs(net_debit_credit)``. A cash-secured put's net is a
   NEGATIVE credit in the seam and a POSITIVE limit on the wire. This is the one
   place the seam does not map 1:1, and submitting the seam's sign here is
   invisible until the broker rejects.
2. **On `mleg` the SIGNED net crosses unchanged** (2c), `ratio_qty` rides each
   leg, and `qty` is order-level (C2). Exactly the mirror of the above, which is
   why they are easy to confuse and why GB-E asserts both.
3. **4b — `position_intent` on every leg, opening-only.** `buy -> buy_to_open`,
   `sell -> sell_to_open`. The `_to_close` intents are reserved vocabulary this
   pipeline does not emit.

**Idempotency is the reason `client_order_id` exists.** It is
``ORDER_ID_PREFIX + <root ledger entry id>`` (shape 4), the root entry is
written before submission so its id exists first, and the prefix is per-box
configuration read from the environment — never a literal in tracked code, since
the two pods share an account and the id is the only thing telling their orders
apart. A submission that times out leaves a caller unable to distinguish "it did
not arrive" from "it arrived and the reply was lost"; retrying blind opens a
second position and refusing to retry leaves an unknown one. Because the id is
derived from the entry, the retry is safe: the broker refuses the duplicate and
:meth:`Executor.submit` resolves it to the order that already exists.

Transport is injectable, and the two implementations satisfy the same
two-method interface so the suite and the real run take the same code path:
``FakeTransport`` in GB-E, :class:`AlpacaPyTransport` — a thin wrapper over
Alpaca's official ``alpaca-py`` ``TradingClient`` — in production. Why an SDK
rather than MCP on this particular path is written up in
``docs/EXECUTION_RATIONALE.md``, which the event FAQ asks for.
"""

from __future__ import annotations

from glassbox.datafeed import assert_paper
from glassbox.ledger import client_order_id as build_client_order_id

__all__ = [
    "Executor", "ExecutorError", "DuplicateOrder", "AlpacaPyTransport",
    "covered_call", "cash_secured_put", "vertical_spread",
    "STRUCTURE_BUILDERS", "POSITION_INTENTS", "BROKER_STATUS_MAP",
]

#: 4b, opening-only for this event. `buy_to_close` / `sell_to_close` are
#: RESERVED and this pipeline never emits them; if early exits are ever added,
#: they use those intents and 4b is the note that gets amended.
POSITION_INTENTS = {"buy": "buy_to_open", "sell": "sell_to_open"}

#: Alpaca order status -> shape 5 entry status. The shape 5 vocabulary is CLOSED
#: (adding a value is a seam change), so a broker state with no word here RAISES
#: rather than being translated into the nearest one we happen to own.
BROKER_STATUS_MAP = {
    "new": "submitted",
    "accepted": "submitted",
    "pending_new": "submitted",
    "accepted_for_bidding": "submitted",
    "partially_filled": "partial_fill",
    "filled": "filled",
    "rejected": "broker_rejected",
    "canceled": "canceled",
    "expired": "expired",
}

_CONTRACT_MULTIPLIER = 100


class ExecutorError(RuntimeError):
    """The executor refused to act, or the broker said something unmappable."""


class DuplicateOrder(ExecutorError):
    """The broker already holds an order under this `client_order_id`.

    Not a failure. It is the id scheme working: the duplicate was refused
    instead of a second position being opened, and the caller resolves it to the
    order that already exists.
    """

    def __init__(self, client_order_id):
        super().__init__(
            f"an order already exists under client_order_id {client_order_id!r}"
        )
        self.client_order_id = client_order_id


# ---------------------------------------------------------------------------
# Structure-tagged constructors — the naked case is unrepresentable
# ---------------------------------------------------------------------------

def _wire_leg(leg):
    action = leg.get("action")
    if action not in POSITION_INTENTS:
        raise ValueError(f"leg action must be 'buy' or 'sell', got {action!r}")
    symbol = leg.get("symbol")
    if not symbol:
        raise ValueError("every leg carries its OCC symbol (2b); an order cannot "
                         "be reconstructed from type/strike/expiry without a "
                         "second source of truth for which contract is traded")
    ratio = leg.get("ratio_qty")
    if not isinstance(ratio, int) or isinstance(ratio, bool) or ratio < 1:
        raise ValueError(f"{symbol}: ratio_qty must be a positive integer")
    return {
        "symbol": symbol,
        "side": action,
        "ratio_qty": ratio,
        "position_intent": POSITION_INTENTS[action],
    }


def _single_leg_payload(leg, qty, net_debit_credit, client_order_id):
    """4a: single-leg, positive limit, direction from side, no order_class."""
    wire = _wire_leg(leg)
    return {
        "client_order_id": client_order_id,
        "symbol": wire["symbol"],
        "qty": qty,
        "side": wire["side"],
        "type": "limit",
        "time_in_force": "day",
        # abs(), always. The seam's sign is carried by `side` on this path, and
        # a negative limit on a single-leg order is never submitted (4a).
        "limit_price": abs(net_debit_credit),
        "position_intent": wire["position_intent"],
    }


def covered_call(*, underlying, leg, qty, net_debit_credit, client_order_id,
                 covering_shares):
    """A covered call. **`covering_shares` is required and has no default.**

    That is the whole point: written as `legs[]`, a covered call and a naked
    call are the same object. The shares are what make it defined-risk, so the
    builder cannot be called without them and checks them when it is.
    """
    _require_single(leg, "call", "sell", "covered_call")
    required = _CONTRACT_MULTIPLIER * qty
    if not isinstance(covering_shares, (int, float)) or covering_shares < required:
        raise ValueError(
            f"covered_call needs {required} shares of {underlying} to cover "
            f"{qty} contract(s); got covering_shares={covering_shares}. A short "
            f"call without the cover is a naked short, and this builder has no "
            f"way to express one"
        )
    return _single_leg_payload(leg, qty, net_debit_credit, client_order_id)


def cash_secured_put(*, underlying, leg, qty, net_debit_credit, client_order_id,
                     securing_cash):
    """A cash-secured put. **`securing_cash` is required and has no default.**

    The same argument as :func:`covered_call`, in the currency a put is secured
    in: strike x 100 x qty, because assignment buys the shares at the strike.
    """
    _require_single(leg, "put", "sell", "cash_secured_put")
    required = leg["strike"] * _CONTRACT_MULTIPLIER * qty
    if not isinstance(securing_cash, (int, float)) or securing_cash < required:
        raise ValueError(
            f"cash_secured_put needs {required:.2f} in cash to secure {qty} "
            f"contract(s) at strike {leg['strike']}; got securing_cash="
            f"{securing_cash}. An unsecured short put is a naked short, and this "
            f"builder has no way to express one"
        )
    return _single_leg_payload(leg, qty, net_debit_credit, client_order_id)


def vertical_spread(*, underlying, legs, qty, net_debit_credit, client_order_id):
    """A defined-risk vertical. Its own long leg is the cover, so there is no
    third argument to forget: a one-legged "vertical" is refused here.
    """
    legs = list(legs)
    if len(legs) != 2:
        raise ValueError(
            f"a vertical_spread is exactly two legs, got {len(legs)}. A lone short "
            f"leg is a naked short wearing a defined-risk label (2e)"
        )
    if len([leg for leg in legs if leg.get("action") == "buy"]) != 1:
        raise ValueError(
            "a vertical_spread has exactly one long leg — it is what bounds the "
            "risk, and without it there is nothing defined about this position"
        )
    return {
        "client_order_id": client_order_id,
        "order_class": "mleg",          # 2+ legs, and only this structure is
        "qty": qty,                     # order-level (C2), never per leg
        "type": "limit",
        "time_in_force": "day",
        # SIGNED, unchanged from the seam: on mleg the sign IS the direction
        # (positive debit, negative credit). The mirror of 4a's abs().
        "limit_price": net_debit_credit,
        "legs": [_wire_leg(leg) for leg in legs],
    }


def _require_single(leg, option_type, action, structure):
    if leg.get("option_type") != option_type or leg.get("action") != action:
        raise ValueError(
            f"{structure} is exactly one {action} {option_type} leg, got "
            f"{leg.get('action')} {leg.get('option_type')}"
        )


#: The whole dispatch surface. It covers exactly the closed structure enum (2a)
#: and there is nothing else in this module that builds an order payload.
STRUCTURE_BUILDERS = {
    "covered_call": covered_call,
    "cash_secured_put": cash_secured_put,
    "vertical_spread": vertical_spread,
}


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------

class Executor:
    """Submits approved verdicts, and writes what happened to the ledger.

    Args:
        ledger: a :class:`glassbox.ledger.Ledger`. Follow-ups are appended to it;
            nothing is ever mutated.
        transport: anything exposing ``submit_order(payload)`` and
            ``get_order_by_client_id(client_order_id)``.
        config: the mapping :func:`glassbox.datafeed.load_config` returns. The
            paper guard reads its trading base URL.
        env: environment mapping the order-id prefix is read from. Defaults to
            the real environment.
    """

    def __init__(self, ledger, transport, config, env=None):
        self.ledger = ledger
        self.transport = transport
        self.config = config
        self.env = env

    # -- building ----------------------------------------------------------

    def build_order_request(self, root_entry, covering_shares=None,
                            securing_cash=None):
        """The wire payload for one approved root entry.

        A pure function of the entry (and, for the two single-leg structures, the
        cover). Two calls give byte-identical payloads including the
        `client_order_id`, which is what makes a retry a retry rather than a
        second order.

        The cover defaults to the entry's OWN account snapshot, so a caller
        cannot accidentally assert cover that the decision was not made against —
        the coverage the governor checked and the coverage the builder requires
        are then the same numbers.
        """
        proposal = root_entry["proposal"]
        structure = proposal["structure"]
        builder = STRUCTURE_BUILDERS.get(structure)
        if builder is None:
            raise ValueError(
                f"structure {structure!r} is outside the closed enum (2a); there "
                f"is no builder for it and there is deliberately no generic one"
            )

        client_order_id = build_client_order_id(root_entry["id"], env=self.env)
        common = dict(underlying=proposal["underlying"], qty=proposal["qty"],
                      net_debit_credit=proposal["net_debit_credit"],
                      client_order_id=client_order_id)

        if structure == "vertical_spread":
            return builder(legs=proposal["legs"], **common)

        account = (root_entry.get("snapshot") or {}).get("account_state") or {}
        leg = proposal["legs"][0]
        if structure == "covered_call":
            if covering_shares is None:
                position = (account.get("positions") or {}).get(proposal["underlying"]) or {}
                covering_shares = position.get("shares", 0) - position.get("reserved_shares", 0)
            return builder(leg=leg, covering_shares=covering_shares, **common)

        if securing_cash is None:
            securing_cash = account.get("cash", 0) - account.get("reserved_cash", 0)
        return builder(leg=leg, securing_cash=securing_cash, **common)

    # -- submitting --------------------------------------------------------

    def submit(self, root_entry, ts, covering_shares=None, securing_cash=None):
        """Submit an approved root entry, and append the `submitted` follow-up.

        Returns ``{"order", "entry", "resolved_existing", "broker"}``.

        Two refusals happen BEFORE the transport is touched at all: an unapproved
        verdict, and a trading base URL that is not paper. A guard that fires
        after the request has left is not a guard.
        """
        verdict = root_entry.get("verdict") or {}
        if not verdict.get("approved"):
            raise ValueError(
                f"entry {root_entry.get('id')!r} was not approved by the governor "
                f"({verdict.get('reason')!r}). The governor is the only component "
                f"that may emit an order (shape 3), and the executor does not "
                f"second-guess it in either direction"
            )
        if root_entry.get("root_id") is not None:
            raise ValueError("only a ROOT entry carries a decision to submit (5a)")

        # Raises before anything capable of reaching a venue is called, and
        # before the prefix is even read, so the order of failures is stable.
        assert_paper(self.config.get("trading_base_url"))

        payload = self.build_order_request(
            root_entry, covering_shares=covering_shares, securing_cash=securing_cash
        )

        resolved_existing = False
        try:
            broker = self.transport.submit_order(payload)
        except DuplicateOrder:
            # The id scheme working exactly as designed (shape 4): the broker
            # refused a second position rather than opening one.
            broker = self.transport.get_order_by_client_id(payload["client_order_id"])
            if broker is None:
                raise ExecutorError(
                    f"the broker refused {payload['client_order_id']!r} as a "
                    f"duplicate but will not return the order it duplicates. Do "
                    f"NOT retry: resolve this by hand before submitting anything "
                    f"else on this account"
                ) from None
            resolved_existing = True

        order = self._order_record(root_entry, payload, broker)
        entry = self.ledger.append_follow_up(
            id=self._follow_up_id(root_entry["id"], "submitted"),
            root_id=root_entry["id"], ts=ts, status="submitted",
            order=order, fill=None,
        )
        return {"order": order, "entry": entry, "broker": broker,
                "resolved_existing": resolved_existing}

    # -- recording what happened next --------------------------------------

    def record_transition(self, root_id, broker_order, ts):
        """Append the follow-up for a broker state change (5a).

        `partial_fill` is NOT terminal, so a chain may pass through it and go on
        to `filled`. An unmapped broker status raises: the shape 5 vocabulary is
        closed, and translating an unknown state into the nearest word we happen
        to own would put a fact in the audit record that nobody ever established.
        """
        raw_status = broker_order.get("status")
        status = BROKER_STATUS_MAP.get(raw_status)
        if status is None:
            raise ValueError(
                f"broker status {raw_status!r} has no mapping into the shape 5 "
                f"vocabulary ({'|'.join(sorted(set(BROKER_STATUS_MAP.values())))}). "
                f"Adding a status value is a seam change, so this stops here "
                f"rather than guessing which one it meant"
            )

        entries = self.ledger.read_entries()
        root = next((e for e in entries if e["id"] == root_id), None)
        if root is None:
            raise ValueError(f"no root entry {root_id!r} in this ledger")

        order = self._order_record(root, None, broker_order)
        return self.ledger.append_follow_up(
            id=self._follow_up_id(root_id, status),
            root_id=root_id, ts=ts, status=status,
            order=order, fill=_fill_of(broker_order),
        )

    # -- internals ---------------------------------------------------------

    def _follow_up_id(self, root_id, status):
        """Deterministic, unique, and readable in a raw JSONL file.

        The chain's own length is the sequence number, so ids do not depend on a
        clock and two follow-ups in the same second cannot collide.
        """
        existing = [e for e in self.ledger.read_entries()
                    if (e["root_id"] or e["id"]) == root_id]
        return f"{root_id}+{len(existing):02d}-{status}"

    @staticmethod
    def _order_record(root_entry, payload, broker):
        """Shape 4, out of what we sent and what the broker said."""
        legs = []
        if payload is not None:
            legs = payload.get("legs") or [{
                "symbol": payload["symbol"], "side": payload["side"],
                "ratio_qty": 1, "position_intent": payload["position_intent"],
            }]
            net_limit = payload["limit_price"]
            qty = payload["qty"]
        else:
            proposal = root_entry.get("proposal") or {}
            legs = [_wire_leg(leg) for leg in proposal.get("legs") or []]
            net_limit = proposal.get("net_debit_credit")
            qty = proposal.get("qty")

        return {
            "client_order_id": broker.get("client_order_id"),
            "order_id": broker.get("id"),
            "status": broker.get("status"),
            "underlying": (root_entry.get("proposal") or {}).get("underlying"),
            "qty": qty,
            "legs": legs,
            "net_limit_price": net_limit,
            "submitted_at": broker.get("submitted_at"),
            "fill": _fill_of(broker) or {},
        }


def _fill_of(broker_order):
    """The fill block, or None when nothing has filled yet."""
    filled_qty = broker_order.get("filled_qty")
    if filled_qty in (None, "", "0", 0):
        return None
    price = broker_order.get("filled_avg_price")
    return {
        "filled_qty": float(filled_qty),
        "filled_avg_price": None if price in (None, "") else float(price),
        "filled_at": broker_order.get("filled_at") or broker_order.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# The real transport — Alpaca's own SDK, and nothing else
# ---------------------------------------------------------------------------

class AlpacaPyTransport:
    """The two-method transport interface, over ``alpaca-py``'s ``TradingClient``.

    Deliberately thin. Everything interesting — the structure-tagged builders,
    the 4a/4b mapping, the id scheme, the ledger chain — happens above this
    class, which exists only so that the real run and the contract suite take
    the same code path through :class:`Executor`.

    ``docs/EXECUTION_RATIONALE.md`` explains why this path is the official SDK
    rather than MCP, as the event FAQ requires.
    """

    def __init__(self, config, client=None):
        assert_paper(config.get("trading_base_url"))
        self.config = config
        if client is not None:
            self.client = client
            return
        from alpaca.trading.client import TradingClient

        self.client = TradingClient(
            api_key=config["api_key"],
            secret_key=config["secret_key"],
            paper=True,          # the guard above has already refused anything else
        )

    def submit_order(self, payload):
        from alpaca.common.exceptions import APIError
        from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

        common = dict(
            client_order_id=payload["client_order_id"],
            qty=payload["qty"],
            limit_price=payload["limit_price"],
            time_in_force=TimeInForce.DAY,
        )
        if payload.get("order_class") == "mleg":
            request = LimitOrderRequest(
                order_class=OrderClass.MLEG,
                legs=[
                    OptionLegRequest(
                        symbol=leg["symbol"],
                        side=OrderSide(leg["side"]),
                        ratio_qty=leg["ratio_qty"],
                        position_intent=PositionIntent(leg["position_intent"]),
                    )
                    for leg in payload["legs"]
                ],
                **common,
            )
        else:
            request = LimitOrderRequest(
                symbol=payload["symbol"],
                side=OrderSide(payload["side"]),
                position_intent=PositionIntent(payload["position_intent"]),
                **common,
            )

        try:
            order = self.client.submit_order(request)
        except APIError as exc:
            # Alpaca refuses a repeated client_order_id. That refusal is the id
            # scheme doing its job, so it is raised as DuplicateOrder rather than
            # as a generic failure the caller might respond to by retrying blind.
            if "client_order_id" in str(exc) and "exist" in str(exc).lower():
                raise DuplicateOrder(payload["client_order_id"]) from None
            raise
        return _as_dict(order)

    def get_order_by_client_id(self, client_order_id):
        from alpaca.common.exceptions import APIError

        try:
            return _as_dict(self.client.get_order_by_client_id(client_order_id))
        except APIError:
            return None


def _as_dict(order):
    """alpaca-py returns a pydantic model or a raw dict, depending on the call."""
    if isinstance(order, dict):
        return order
    for attribute in ("model_dump", "dict"):
        if hasattr(order, attribute):
            return {k: (str(v) if hasattr(v, "value") else v)
                    for k, v in getattr(order, attribute)().items()}
    return dict(order)
