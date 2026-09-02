"""GB-E — executor contract suite.

The acceptance gate for the executor: the component that turns an approved
verdict into a real order, and the last one before money moves. Everything
upstream of it has been arguing about whether a trade is safe; this is the part
that does it.

Two bands:

  GB-E-F**  fixture integrity — runs today, guards the fixtures.
  GB-E-**   executor behaviour — xfail until glassbox/executor.py lands, then
            runs for real automatically (see conftest.requires_executor).

**No test here reaches a broker.** The transport is injectable and GB-E passes a
`FakeTransport` that records every payload; where the executor must stop *before*
the wire, it passes a `RefusingTransport` that fails the test if it is reached at
all, because "it raised" is a weaker claim than "it raised and nothing was sent".

The interfaces under test are GB_INTERFACES.md **shape 4** (the order), **4a**
(single-leg structures are NOT mleg), **4b** (`position_intent`, opening-only),
**2e** (naked-short prevention lives in the builder, not the schema), and
**5a** (append-only follow-ups chained on `root_id`).

The property this suite exists to defend, above all others: **a naked short
option is not expressible.** Not "is rejected" — not representable. A covered
call and a naked call are the same `legs[]`; only the account state behind them
differs, and the seam says so in normative text (2e). So the builder takes the
covering asset as a REQUIRED argument, and there is no public name in the module
that will build a lone short leg without one. GB-E-01, -02 and -03 are that
claim, made three ways.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import (
    CLOSING_INTENTS,
    EXECUTOR,
    FakeTransport,
    POSITION_INTENTS,
    RefusingTransport,
    requires_executor,
)
from conftest import LEDGER as LEDGER_MOD

PREFIX = "tkc-"
TS = datetime(2026, 9, 2, 13, 45, 2, tzinfo=timezone.utc)

PAPER_CONFIG = {
    "api_key": "NOT-A-KEY",
    "secret_key": "NOT-A-SECRET",
    "trading_base_url": "https://paper-api.alpaca.markets",
    "data_base_url": "https://data.alpaca.markets",
}
LIVE_CONFIG = dict(PAPER_CONFIG, trading_base_url="https://api.alpaca.markets")


@pytest.fixture()
def env():
    """A per-box environment carrying the order-id prefix. Never a literal in code."""
    return {"ORDER_ID_PREFIX": PREFIX}


@pytest.fixture()
def ledger(tmp_path, entries):
    """A real Ledger over a temp copy of the GB-L goldens.

    A temp copy, not the committed file: an append-only ledger that a test wrote
    to would be a committed fixture that changes every time the suite runs.
    """
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "".join(LEDGER_MOD.serialize(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return LEDGER_MOD.Ledger(path)


def make_executor(ledger, transport, env, config=None):
    return EXECUTOR.Executor(
        ledger=ledger, transport=transport, config=config or PAPER_CONFIG, env=env
    )


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_e_f01_approved_roots_cover_every_structure(approved_roots):
    """GB-E-F01: the executor's inputs exercise all three structures in the enum.

    A suite that only ever builds verticals proves nothing about the two
    single-leg structures, which are the ones 4a treats differently and the ones
    that look like naked shorts on the page.
    """
    assert set(approved_roots) == {"covered_call", "cash_secured_put", "vertical_spread"}
    for structure, root in approved_roots.items():
        assert root["root_id"] is None, "an executor input is a ROOT entry (5a)"
        assert root["verdict"]["approved"] is True
        assert root["order"] is None and root["fill"] is None, (
            "the root is written PRE-submission; the order embeds ITS id, not the "
            "other way round"
        )
        assert root["proposal"]["structure"] == structure


def test_gb_e_f02_broker_responses_match_the_wire(broker_responses):
    """GB-E-F02: the canned bodies are Alpaca order shape, defects included."""
    for name in ("accepted", "filled", "partially_filled", "rejected"):
        body = broker_responses[name]
        for field in ("id", "client_order_id", "status", "qty", "filled_qty",
                      "filled_avg_price", "limit_price", "submitted_at"):
            assert field in body, f"{name} missing {field}"
        assert body["status"] == ("partially_filled" if name == "partially_filled"
                                  else name)
        # Numerics are STRINGS on this endpoint, as everywhere else in Alpaca.
        assert isinstance(body["qty"], str)
        assert body["filled_avg_price"] is None or isinstance(body["filled_avg_price"], str)

    assert broker_responses["filled"]["filled_qty"] == broker_responses["filled"]["qty"]
    partial = broker_responses["partially_filled"]
    assert 0 < float(partial["filled_qty"]) < float(partial["qty"]), (
        "a partial fill fixture that is not actually partial tests nothing"
    )
    assert "HAND-AUTHORED" in broker_responses["_status"]


# ---------------------------------------------------------------------------
# GB-E-01..04 — a naked short is not expressible
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_01_covered_call_requires_the_covering_shares(approved_roots, env):
    """GB-E-01: the constructor will not build without the shares behind it."""
    root = approved_roots["covered_call"]
    proposal = root["proposal"]
    common = dict(underlying=proposal["underlying"], leg=proposal["legs"][0],
                  qty=proposal["qty"],
                  net_debit_credit=proposal["net_debit_credit"],
                  client_order_id="tkc-x")

    # Omitting the cover is a TypeError, not a validation message: the argument
    # has no default, so the naked case cannot be spelled.
    with pytest.raises(TypeError):
        EXECUTOR.covered_call(**common)

    payload = EXECUTOR.covered_call(**common, covering_shares=100)
    assert payload["symbol"] == proposal["legs"][0]["symbol"]


@requires_executor
def test_gb_e_02_cash_secured_put_requires_the_securing_cash(approved_roots, env):
    """GB-E-02: the same argument, in the currency a put is secured in."""
    root = approved_roots["cash_secured_put"]
    proposal = root["proposal"]
    common = dict(underlying=proposal["underlying"], leg=proposal["legs"][0],
                  qty=proposal["qty"],
                  net_debit_credit=proposal["net_debit_credit"],
                  client_order_id="tkc-x")

    with pytest.raises(TypeError):
        EXECUTOR.cash_secured_put(**common)

    strike = proposal["legs"][0]["strike"]
    payload = EXECUTOR.cash_secured_put(**common, securing_cash=strike * 100 * proposal["qty"])
    assert payload["symbol"] == proposal["legs"][0]["symbol"]


@requires_executor
def test_gb_e_03_no_public_name_builds_a_lone_short_leg(approved_roots):
    """GB-E-03: 2e's invariant, checked against the module's whole surface.

    The seam is explicit that naked-short prevention is NOT a property of the
    schema and cannot be: a covered call IS a lone short call leg. It is a
    property of THIS module's API. So the API must not contain a general-purpose
    single-leg builder that a hurried caller could reach for at 2am on submission
    day — and the check for that is the exported surface, not a comment.
    """
    builders = {name for name in EXECUTOR.__all__
                if name in ("covered_call", "cash_secured_put", "vertical_spread")}
    assert builders == {"covered_call", "cash_secured_put", "vertical_spread"}

    forbidden = ("single_leg", "naked", "short_call", "short_put", "build_leg",
                 "raw_order", "submit_raw")
    for name in EXECUTOR.__all__:
        assert not any(bad in name for bad in forbidden), (
            f"{name} is a way to build an uncovered leg without saying so"
        )
    assert EXECUTOR.STRUCTURE_BUILDERS.keys() == builders, (
        "dispatch covers exactly the closed enum (2a) and nothing else"
    )


@requires_executor
def test_gb_e_04_insufficient_cover_is_refused(approved_roots):
    """GB-E-04: the argument exists to be CHECKED, not merely to be passed."""
    call = approved_roots["covered_call"]["proposal"]
    with pytest.raises(ValueError, match="cover"):
        EXECUTOR.covered_call(
            underlying=call["underlying"], leg=call["legs"][0], qty=call["qty"],
            net_debit_credit=call["net_debit_credit"], client_order_id="tkc-x",
            covering_shares=99,          # one share short of one contract
        )

    put = approved_roots["cash_secured_put"]["proposal"]
    strike = put["legs"][0]["strike"]
    with pytest.raises(ValueError, match="secur"):
        EXECUTOR.cash_secured_put(
            underlying=put["underlying"], leg=put["legs"][0], qty=put["qty"],
            net_debit_credit=put["net_debit_credit"], client_order_id="tkc-x",
            securing_cash=strike * 100 * put["qty"] - 0.01,
        )


# ---------------------------------------------------------------------------
# GB-E-05..08 — the wire mapping, 4a and 4b
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_05_single_leg_structures_are_not_mleg(approved_roots, env, ledger,
                                                    broker_responses):
    """GB-E-05: 4a — covered_call and cash_secured_put go out as single-leg orders.

    `mleg` requires two or more legs. Only a vertical is one.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    for structure in ("covered_call", "cash_secured_put"):
        payload = executor.build_order_request(approved_roots[structure])
        assert "order_class" not in payload or payload["order_class"] != "mleg"
        assert "legs" not in payload, "a single-leg order carries no legs[] array"
        assert payload["symbol"], "it carries the contract symbol directly"
        assert payload["type"] == "limit" and payload["time_in_force"] == "day"


@requires_executor
def test_gb_e_06_a_single_leg_limit_price_is_never_negative(approved_roots, env,
                                                            ledger, broker_responses):
    """GB-E-06: 4a — `limit_price = abs(net)`, direction from `side`.

    This is the ONE place the seam does not map 1:1 to the wire. A cash-secured
    put's net is a NEGATIVE credit in the seam and a POSITIVE limit on the wire,
    with `sell` carrying the direction. Submitting the seam's sign here is the
    mistake 4a exists to prevent, and it is invisible until the broker rejects.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)

    for structure in ("covered_call", "cash_secured_put"):
        proposal = approved_roots[structure]["proposal"]
        assert proposal["net_debit_credit"] < 0, (
            "fixture check: both of these collect a credit, so the sign flip is live"
        )
        payload = executor.build_order_request(approved_roots[structure])
        assert payload["limit_price"] == abs(proposal["net_debit_credit"])
        assert payload["limit_price"] > 0
        assert payload["side"] == proposal["legs"][0]["action"]


@requires_executor
def test_gb_e_07_position_intent_is_on_every_leg_and_opening_only(approved_roots,
                                                                  env, ledger,
                                                                  broker_responses):
    """GB-E-07: 4b — buy -> buy_to_open, sell -> sell_to_open, and never a close."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)

    for structure, root in approved_roots.items():
        payload = executor.build_order_request(root)
        legs = payload.get("legs") or [payload]
        proposal_legs = root["proposal"]["legs"]
        assert len(legs) == len(proposal_legs)
        for wire, proposal_leg in zip(legs, proposal_legs):
            assert wire["position_intent"] == POSITION_INTENTS[proposal_leg["action"]]
            assert wire["position_intent"] not in CLOSING_INTENTS

        # _to_close is reserved vocabulary this pipeline does not emit at all.
        text = json.dumps(payload)
        for intent in CLOSING_INTENTS:
            assert intent not in text, f"{structure}: {intent} must not appear"


@requires_executor
def test_gb_e_08_a_vertical_goes_out_as_mleg_with_a_signed_net(approved_roots, env,
                                                               ledger, broker_responses):
    """GB-E-08: mleg carries ratio_qty per leg, qty at the ORDER, and a SIGNED net.

    The mirror of GB-E-06: on a multi-leg order the sign is the direction and
    must survive, where on a single-leg order it must not appear at all.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["vertical_spread"]
    proposal = root["proposal"]
    payload = executor.build_order_request(root)

    assert payload["order_class"] == "mleg"
    assert payload["qty"] == proposal["qty"], "qty is order-level (C2), not per leg"
    assert payload["limit_price"] == proposal["net_debit_credit"], (
        "the signed net crosses to the wire unchanged for mleg (2c)"
    )
    assert len(payload["legs"]) == 2
    for wire, proposal_leg in zip(payload["legs"], proposal["legs"]):
        assert wire["symbol"] == proposal_leg["symbol"]
        assert wire["side"] == proposal_leg["action"]
        assert wire["ratio_qty"] == proposal_leg["ratio_qty"]
        assert "qty" not in wire, "a leg carries ratio_qty, never qty"


# ---------------------------------------------------------------------------
# GB-E-09..12 — identity, and the two guards
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_09_client_order_id_is_the_prefix_plus_the_root_id(approved_roots, env,
                                                                ledger, broker_responses):
    """GB-E-09: shape 4's id scheme, which is what makes a retry safe."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    for root in approved_roots.values():
        payload = executor.build_order_request(root)
        assert payload["client_order_id"] == PREFIX + root["id"]


@requires_executor
def test_gb_e_10_a_missing_prefix_raises_and_submits_nothing(approved_roots, ledger,
                                                             broker_responses):
    """GB-E-10: the prefix is per-box configuration; an unset one is not a default.

    The two pods share an account. A prefix defaulted in code would put one pod's
    marker on the other pod's orders, and the id is the only thing distinguishing
    them in the broker's blotter.
    """
    transport = RefusingTransport()
    executor = make_executor(ledger, transport, env={})
    with pytest.raises(ValueError, match="ORDER_ID_PREFIX"):
        executor.submit(approved_roots["covered_call"], ts=TS)
    assert transport.submitted == []


@requires_executor
def test_gb_e_11_no_order_id_prefix_literal_is_in_tracked_code():
    """GB-E-11: the prefix is never hardcoded (CLAUDE.md, shape 4) — grep, not trust.

    The mirror of GB-L-07, extended to the executor: a literal that appears in a
    default argument, or in a docstring someone later copies, is the way this
    rule actually breaks.
    """
    import pathlib

    package = pathlib.Path(EXECUTOR.__file__).parent
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal in ('"tkc-"', "'tkc-'", '"jho-"', "'jho-'"):
            assert literal not in text, f"{path.name} hardcodes an order-id prefix"


@requires_executor
def test_gb_e_12_the_paper_guard_fires_before_any_submission(approved_roots, env,
                                                             ledger):
    """GB-E-12: paper-only (CLAUDE.md), on the write path as well as the read path."""
    transport = RefusingTransport()
    executor = make_executor(ledger, transport, env, config=LIVE_CONFIG)
    with pytest.raises(Exception, match="paper"):
        executor.submit(approved_roots["covered_call"], ts=TS)
    assert transport.submitted == []


@requires_executor
def test_gb_e_13_an_unapproved_verdict_is_never_submitted(rejected_root, env, ledger):
    """GB-E-13: the governor is the gate, and the executor does not second-guess it.

    The executor has no opinion about risk. It has exactly one opinion about
    approval: if the verdict says no, nothing leaves.
    """
    transport = RefusingTransport()
    executor = make_executor(ledger, transport, env)
    with pytest.raises(ValueError, match="approv"):
        executor.submit(rejected_root, ts=TS)
    assert transport.submitted == []


# ---------------------------------------------------------------------------
# GB-E-14..15 — idempotency
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_14_a_retry_carries_the_same_client_order_id(approved_roots, env,
                                                          ledger, broker_responses):
    """GB-E-14: the id is derived from the root entry, so it is stable across retries."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["cash_secured_put"]

    first = executor.build_order_request(root)
    second = executor.build_order_request(root)
    assert first["client_order_id"] == second["client_order_id"] == PREFIX + root["id"]
    assert first == second, "the built order is a function of the entry, nothing else"


@requires_executor
def test_gb_e_15_a_duplicate_resolves_to_the_existing_order(approved_roots, env,
                                                            ledger, broker_responses):
    """GB-E-15: the point of the whole id scheme — never a second position.

    A submission that times out leaves the caller unable to tell "it did not
    arrive" from "it arrived and the reply was lost". Retrying blind opens a
    second position; refusing to retry leaves an unknown one. The id makes the
    retry safe: the broker refuses the duplicate, and the executor resolves it to
    the order that already exists rather than treating the refusal as a failure.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["vertical_spread"]

    first = executor.submit(root, ts=TS)
    assert len(transport.submitted) == 1

    second = executor.submit(root, ts=TS)
    assert second["order"]["order_id"] == first["order"]["order_id"], (
        "the retry resolved to the SAME broker order"
    )
    assert len(transport.orders) == 1, "exactly one order exists at the broker"
    assert second["resolved_existing"] is True, (
        "and the caller is told it was a resolution, not a fresh submission"
    )


# ---------------------------------------------------------------------------
# GB-E-16..19 — the ledger chain (5a)
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_16_submission_appends_a_follow_up_on_the_root(approved_roots, env,
                                                            ledger, broker_responses):
    """GB-E-16: 5a — a transition is a new appended entry carrying `root_id`."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["covered_call"]
    before = len(ledger.read_entries())

    result = executor.submit(root, ts=TS)
    entries = ledger.read_entries()
    assert len(entries) == before + 1

    follow_up = entries[-1]
    assert follow_up["root_id"] == root["id"], "chains fold on the ROOT id"
    assert follow_up["status"] == "submitted"
    assert follow_up["order"] is not None
    assert follow_up["fill"] is None, "no fill has happened yet, and null says so"
    assert follow_up["proposal"] is None and follow_up["verdict"] is None, (
        "the decision lives on the root; a follow-up records a transition"
    )
    assert follow_up["order"]["client_order_id"] == PREFIX + root["id"]
    assert result["entry"]["id"] == follow_up["id"]

    # The root itself is untouched, byte for byte. Append-only is not a
    # convention here, it is the thing the ledger is for.
    assert entries[[e["id"] for e in entries].index(root["id"])] == root


@requires_executor
def test_gb_e_17_terminal_and_non_terminal_transitions(approved_roots, env, ledger,
                                                       broker_responses):
    """GB-E-17: filled, partial_fill and broker_rejected, and which of them end.

    `partial_fill` is deliberately NOT terminal (5a): Alpaca's partially_filled
    is not an end state, and a chain sitting on one may still reach filled.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["vertical_spread"]
    executor.submit(root, ts=TS)

    partial = dict(broker_responses["partially_filled"],
                   client_order_id=PREFIX + root["id"])
    executor.record_transition(root["id"], partial, ts=TS)
    entries = ledger.read_entries()
    status, terminal = LEDGER_MOD.current_status(entries, root["id"])
    assert status == "partial_fill" and terminal is False

    filled = dict(broker_responses["filled"], client_order_id=PREFIX + root["id"])
    executor.record_transition(root["id"], filled, ts=TS)
    entries = ledger.read_entries()
    status, terminal = LEDGER_MOD.current_status(entries, root["id"])
    assert status == "filled" and terminal is True

    fill = entries[-1]["fill"]
    assert fill and fill["filled_qty"] == float(broker_responses["filled"]["filled_qty"])
    assert fill["filled_avg_price"] == float(broker_responses["filled"]["filled_avg_price"])


@requires_executor
def test_gb_e_18_a_broker_rejection_is_not_a_governor_rejection(approved_roots, env,
                                                                ledger, broker_responses):
    """GB-E-18: "we refused" and "they refused" are different facts (5a)."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["cash_secured_put"]
    executor.submit(root, ts=TS)

    rejected = dict(broker_responses["rejected"], client_order_id=PREFIX + root["id"])
    executor.record_transition(root["id"], rejected, ts=TS)
    entries = ledger.read_entries()
    status, terminal = LEDGER_MOD.current_status(entries, root["id"])
    assert status == "broker_rejected" and terminal is True
    assert status != "governor_rejected"


@requires_executor
def test_gb_e_19_an_unknown_broker_status_raises(approved_roots, env, ledger,
                                                 broker_responses):
    """GB-E-19: the shape 5 vocabulary is closed; an unmapped status is not guessed.

    Adding a status value is a seam change. A broker state we have no word for is
    a stop, not a best-effort translation into the nearest one we do have.
    """
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["covered_call"]
    executor.submit(root, ts=TS)

    weird = dict(broker_responses["accepted"], status="held_for_review",
                 client_order_id=PREFIX + root["id"])
    with pytest.raises(ValueError, match="held_for_review"):
        executor.record_transition(root["id"], weird, ts=TS)


@requires_executor
def test_gb_e_20_the_chain_folds_and_the_provenance_rides_it(approved_roots, env,
                                                             ledger, broker_responses):
    """GB-E-20: one position, one chain, one provenance block."""
    transport = FakeTransport(broker_responses)
    executor = make_executor(ledger, transport, env)
    root = approved_roots["vertical_spread"]
    executor.submit(root, ts=TS)
    executor.record_transition(
        root["id"], dict(broker_responses["filled"], client_order_id=PREFIX + root["id"]),
        ts=TS,
    )

    entries = ledger.read_entries()
    chain = LEDGER_MOD.fold_chain(entries, root["id"])
    assert [e["status"] for e in chain["entries"]][-2:] == ["submitted", "filled"]
    for link in chain["entries"][1:]:
        for field in ("as_of", "mode", "config_version", "prompt_version",
                      "code_version"):
            assert link[field] == root[field], (
                f"{field} drifted inside a chain; it is read from the root, not "
                f"restated by the caller"
            )


# ---------------------------------------------------------------------------
# GB-E-21 — the real transport
# ---------------------------------------------------------------------------

@requires_executor
def test_gb_e_21_the_real_transport_is_the_official_sdk_and_is_paper_only():
    """GB-E-21: AlpacaPyTransport wraps alpaca-py, and refuses a live URL.

    Constructing it opens no socket, so this runs in the same suite as everything
    else. The FAQ permits an SDK when official SDKs are prioritized and the
    reasons are explained (docs/EXECUTION_RATIONALE.md); this is the assertion
    that the SDK in question is actually Alpaca's.
    """
    pytest.importorskip("alpaca.trading.client")

    with pytest.raises(Exception, match="paper"):
        EXECUTOR.AlpacaPyTransport(LIVE_CONFIG)

    transport = EXECUTOR.AlpacaPyTransport(PAPER_CONFIG)
    assert type(transport.client).__module__.startswith("alpaca."), (
        "the transport must wrap Alpaca's own client, not a hand-rolled one"
    )
    for method in ("submit_order", "get_order_by_client_id"):
        assert callable(getattr(transport, method)), (
            f"the real transport must satisfy the same two-method interface the "
            f"FakeTransport does, or the suite is testing a different code path"
        )


@requires_executor
def test_gb_e_22_sdk_models_normalise_to_primitives(approved_roots):
    """GB-E-22: the real transport's model conversion, which the fake cannot test.

    `FakeTransport` returns plain dicts, so every test above this one exercises
    a path where conversion is a no-op. The real transport returns an alpaca-py
    pydantic model, and two of its properties are hostile:

      * its enums are `class X(str, Enum)`, so on Python 3.11+ `str(...)` yields
        `'OrderStatus.ACCEPTED'` rather than `'accepted'` — which would reach
        BROKER_STATUS_MAP as an unmapped word and make the executor refuse an
        ordinary fill, live and only live;
      * it carries real `datetime` objects, and a ledger entry is serialized
        with `json.dumps`, which cannot encode one — failing the append AFTER
        the order is already at the broker.

    Both are invisible until a real order exists. This is the test that makes
    them visible without one.
    """
    from datetime import datetime, timezone
    from enum import Enum

    from pydantic import BaseModel

    class Status(str, Enum):
        ACCEPTED = "accepted"

    class OrderLike(BaseModel):
        status: Status
        submitted_at: datetime
        filled_avg_price: float | None = None

    assert str(Status.ACCEPTED) != "accepted", (
        "if this ever stops being true the trap is gone, and so is the reason "
        "for this test — check the conversion still does the right thing anyway"
    )

    converted = EXECUTOR._as_dict(
        OrderLike(status=Status.ACCEPTED,
                  submitted_at=datetime(2026, 9, 2, 13, 45, tzinfo=timezone.utc))
    )
    assert converted["status"] == "accepted", "the enum's VALUE, not its repr"
    assert converted["status"] in EXECUTOR.BROKER_STATUS_MAP
    assert isinstance(converted["submitted_at"], str)
    json.dumps(converted)   # raises if anything survived as a non-primitive

    # A plain dict passes through untouched, which is what keeps the fake and
    # the real transport on the same code path.
    assert EXECUTOR._as_dict({"status": "filled"}) == {"status": "filled"}
