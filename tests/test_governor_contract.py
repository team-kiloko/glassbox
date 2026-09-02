"""GB-C — governor contract suite.

The acceptance gate for the governor (CLAUDE.md: "a module merges when its suite
passes"), and the deepest suite in the system by design — the governor is the
only component that may emit an order, and the only one standing between an LLM's
opinion and a real position.

Its non-negotiable behaviours:

  * It **computes max loss itself** and never trusts `claimed_max_loss`.
  * A **naked short is unapprovable**: `structure` must match leg composition,
    and coverage is checked against account state, not against the schema.
  * It is **deterministic**: no clock, no randomness, no file I/O, thresholds
    passed in by the caller.
  * The verdict is an **audit record**: every check appears with `rule`,
    `passed`, and a `detail` carrying the numbers the decision turned on.

Two bands:

  GB-C-F**  fixture integrity — runs today, must pass. Guards the golden data.
  GB-C-**   governor behaviour — xfail until glassbox/governor.py lands, then
            runs for real automatically (see conftest.requires_governor).

Rule names come from the pinned core vocabulary in GB_INTERFACES.md 3a, which is
the authority; non-seam checks ride the agreed `x_` prefix.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from conftest import (
    CORE_RULES,
    OCC,
    checks_map,
    detail_fields,
    detail_for,
    money,
    net_from_legs,
    requires_governor,
    run_case,
    run_governor,
)

STRUCTURE_ENUM = ("covered_call", "cash_secured_put", "vertical_spread")

#: Half a cent. Money comparisons in this suite are exact to the cent; this is
#: float slack, not a tolerance anyone may tune.
CENT = 0.005


@pytest.fixture()
def govern(proposals, account_states, clocks, gov_thresholds, gov_config_version):
    """Run a case by golden-case name, or by explicit fixture names."""

    def _run(case_name=None, *, proposal=None, account=None, clock="open",
             mode="approve", thresholds=None, config_version=None, golden=None):
        if case_name is not None:
            case = golden["cases"][case_name]
        else:
            case = {"proposal": proposal, "account": account, "clock": clock,
                    "mode": mode}
        return run_case(
            case, proposals, account_states, clocks,
            thresholds if thresholds is not None else gov_thresholds,
            config_version if config_version is not None else gov_config_version,
        )

    return _run


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_c_f01_proposals_match_seam_shape_2(proposals):
    """GB-C-F01: every proposal is a well-formed shape 2, defects and all.

    A defective fixture must be defective in exactly the way it claims. A
    proposal that is malformed by accident tests nothing.
    """
    required = {"underlying", "structure", "qty", "legs", "net_debit_credit",
                "rationale", "claimed_max_loss", "claimed_max_gain"}
    leg_required = {"symbol", "action", "option_type", "strike", "expiry",
                    "ratio_qty", "limit_price"}

    for name, proposal in proposals.items():
        assert not required - set(proposal), f"{name} missing {sorted(required - set(proposal))}"
        assert isinstance(proposal["qty"], int) and proposal["qty"] > 0
        assert proposal["legs"], f"{name} has no legs"

        for leg in proposal["legs"]:
            assert not leg_required - set(leg), f"{name} leg missing fields"
            assert leg["action"] in ("buy", "sell")
            assert leg["option_type"] in ("call", "put")
            assert isinstance(leg["ratio_qty"], int) and leg["ratio_qty"] > 0
            assert leg["limit_price"] > 0, "a limit price is a positive per-share price"

            # The OCC symbol must agree with the structured fields beside it, or
            # the governor's output cannot become an order against the right
            # contract (2b).
            match = OCC.match(leg["symbol"])
            assert match, f"{name}: {leg['symbol']} is not a valid OCC symbol"
            assert match["cp"] == leg["option_type"][0].upper()
            assert float(match["strike"]) / 1000 == float(leg["strike"])
            assert f"20{match['yy']}-{match['mm']}-{match['dd']}" == leg["expiry"]

    # Exactly one proposal is out of the closed enum, and it is the named one.
    out_of_enum = {n for n, p in proposals.items() if p["structure"] not in STRUCTURE_ENUM}
    assert out_of_enum == {"iron_condor_out_of_enum"}


def test_gb_c_f02_account_states_match_seam_shape_2b(account_states):
    """GB-C-F02: raw broker state and the governor's composed view stay distinct.

    A2 (b): the data layer reports raw state only; reservations are the
    governor's, derived from the ledger. A fixture that blurred the two would
    quietly license the governor to accept whatever the data layer says.
    """
    for name, state in account_states.items():
        assert {"as_of", "cash", "buying_power", "positions"} <= set(state), name
        _parse(state["as_of"])

        if name.startswith("raw_"):
            assert "reserved_cash" not in state, f"{name} is raw: no reservations"
            assert "ledger" not in state, f"{name} is raw: no ledger-derived block"
            for position in state["positions"].values():
                assert set(position) == {"shares"}, f"{name} is raw: shares only"
            continue

        assert name.startswith("composed_"), f"{name}: name it raw_ or composed_"
        assert "reserved_cash" in state, f"{name} is composed: reservations required"
        for position in state["positions"].values():
            assert {"shares", "reserved_shares"} <= set(position), name
            assert position["reserved_shares"] <= position["shares"], (
                f"{name}: more shares reserved than held"
            )
        ledger = state["ledger"]
        assert {"open_positions", "recent_activity"} <= set(ledger), name
        for activity in ledger["recent_activity"].values():
            assert {"last_open_at", "position_opened_at"} <= set(activity), name
            for value in activity.values():
                if value is not None:
                    _parse(value)

    assert any(n.startswith("raw_") for n in account_states), "keep a raw fixture"


def test_gb_c_f03_clocks_match_alpaca_shape(clocks):
    """GB-C-F03: the clock fixtures are a real /v2/clock shape, one open one closed."""
    for name, clock in clocks.items():
        assert {"timestamp", "is_open", "next_open", "next_close"} <= set(clock), name
        assert isinstance(clock["is_open"], bool)
        _parse(clock["timestamp"])
    assert clocks["open"]["is_open"] is True
    assert clocks["closed"]["is_open"] is False


def test_gb_c_f04_golden_is_total_and_uses_the_pinned_vocabulary(
    gov_golden, proposals, account_states, clocks
):
    """GB-C-F04: the golden file is total, well-formed, and on-vocabulary."""
    core = set(gov_golden["rule_vocabulary"]["core"])
    assert core == set(CORE_RULES), (
        "the core checks[] vocabulary is pinned in GB_INTERFACES.md 3a; "
        "changing it is a seam change, not a fixture edit"
    )
    extensions = set(gov_golden["rule_vocabulary"]["extensions"])
    assert all(rule.startswith("x_") for rule in extensions), (
        "non-seam checks ride the x_ prefix (3a)"
    )

    cases = gov_golden["cases"]
    assert cases, "golden must not be empty"
    for name, case in cases.items():
        assert case["proposal"] in proposals, f"{name}: unknown proposal"
        assert case["account"] in account_states, f"{name}: unknown account state"
        assert case["clock"] in clocks, f"{name}: unknown clock"
        assert case["mode"] in ("approve", "autopilot"), f"{name}: bad mode"
        assert not case["account"].startswith("raw_"), (
            f"{name}: the governor takes its composed view, never raw broker state"
        )
        assert set(case["checks"]) == core | extensions, (
            f"{name}: every case states every check"
        )
        # approved is a derived fact, not an independent opinion.
        assert case["approved"] is all(case["checks"].values()), (
            f"{name}: approved disagrees with its own checks"
        )

    # Every structure in the enum is exercised by an APPROVED case, or the suite
    # only proves the governor can say no.
    approved_structures = {
        proposals[c["proposal"]]["structure"] for c in cases.values() if c["approved"]
    }
    assert approved_structures == set(STRUCTURE_ENUM)

    # Every check in the vocabulary is exercised as a failure by some case, or
    # the suite has a rule it never actually tests.
    for rule in core | extensions:
        assert any(not c["checks"][rule] for c in cases.values()), (
            f"no case exercises a {rule} failure"
        )


def test_gb_c_f05_the_fixture_arithmetic_is_what_it_claims(
    gov_golden, proposals, gov_thresholds
):
    """GB-C-F05: the golden's numbers are independently true of the raw legs.

    This is the guard that keeps the golden file honest without the governor:
    the reconciliation is recomputed here from `legs[]`, and the false-claim
    fixture is checked to really be a false claim.
    """
    tolerance = 0.005
    mismatched = set()
    for name, proposal in proposals.items():
        computed = net_from_legs(proposal)
        if abs(computed - proposal["net_debit_credit"]) > tolerance:
            mismatched.add(name)

    # Exactly one proposal is deliberately unreconciled, and it is the qty trap:
    # the reported net is the per-share net multiplied by qty.
    assert mismatched == {"net_mismatch_qty_factor"}
    trap = proposals["net_mismatch_qty_factor"]
    assert trap["qty"] > 1
    assert abs(trap["net_debit_credit"] - net_from_legs(trap) * trap["qty"]) <= tolerance

    # The false-claim fixture must really understate its risk, or it proves nothing.
    liar = proposals["false_claim_debit_vertical"]
    true_max_loss = net_from_legs(liar) * 100 * liar["qty"]
    assert liar["claimed_max_loss"] < true_max_loss
    golden_case = gov_golden["cases"]["false_claim_rejected_by_computed_figure"]
    assert abs(golden_case["computed_max_loss"] - true_max_loss) <= tolerance
    assert golden_case["checks"]["max_loss_cap"] is False

    # And the claim, if believed, would have passed the cap. That is the trap.
    cap = gov_thresholds["max_loss_cap"]["vertical_spread"]
    assert liar["claimed_max_loss"] < cap < true_max_loss


def test_gb_c_f06_thresholds_are_proposed_and_complete(gov_thresholds):
    """GB-C-F06: the config carries every tunable the checks need, and says it is PROPOSED."""
    assert "PROPOSED" in gov_thresholds["_status"]
    for key in ("max_loss_cap", "net_reconcile_tolerance", "cash_floor_pct",
                "churn_window_seconds", "min_hold_seconds", "position_caps"):
        assert key in gov_thresholds, f"missing tunable {key}"

    caps = gov_thresholds["max_loss_cap"]
    for structure in STRUCTURE_ENUM:
        assert structure in caps, f"no cap entry for {structure}"
    assert caps["covered_call"] is None, (
        "a covered call's downside is bounded by the shares behind it; the check "
        "is coverage, not a standalone max-loss cap"
    )
    assert caps["vertical_spread"] == 500.00
    assert gov_thresholds["min_hold_seconds"] > gov_thresholds["churn_window_seconds"], (
        "the two limits are deliberately different so a fixture can sit between them"
    )
    assert {"max_open_positions", "max_open_per_underlying"} <= set(
        gov_thresholds["position_caps"]
    )


# ---------------------------------------------------------------------------
# Governor behaviour — xfail until the module lands
# ---------------------------------------------------------------------------

@requires_governor
def test_gb_c_01_structure_enum_is_closed(govern, gov_golden):
    """GB-C-01: a structure outside the closed enum is rejected, never passed through.

    A1 Option B: `iron_condor` is not in the seam. A condor is two verticals,
    composed by the strategist, and never crosses as one structure.
    """
    verdict = govern("iron_condor_rejected_out_of_enum", golden=gov_golden)
    assert checks_map(verdict)["structure_valid"] is False
    assert verdict["approved"] is False
    assert "iron_condor" in detail_for(verdict, "structure_valid")


@requires_governor
def test_gb_c_02_lone_short_leg_is_not_a_vertical(govern, gov_golden):
    """GB-C-02: THE naked-short trap. A lone short leg declared a vertical fails.

    2e: naked-short prevention is not a schema property. The declared structure
    must match the actual leg composition, or a naked short call walks through
    the governor wearing a defined-risk label.
    """
    verdict = govern("lone_short_leg_rejected", golden=gov_golden)
    assert checks_map(verdict)["structure_valid"] is False
    assert verdict["approved"] is False


@requires_governor
def test_gb_c_03_ratio_qty_must_be_simplest_form(govern, gov_golden):
    """GB-C-03: leg ratio_qty are positive integers with GCD 1 (C2)."""
    verdict = govern("ratio_gcd_rejected", golden=gov_golden)
    assert checks_map(verdict)["structure_valid"] is False
    assert verdict["approved"] is False


@requires_governor
def test_gb_c_04_net_reconciles_per_share_with_no_qty_factor(
    govern, gov_golden, proposals
):
    """GB-C-04: the C1 rule, per share, for ONE unit. `qty` is not a factor.

    The trap is a proposal whose reported net is the per-share net multiplied by
    `qty`. A governor that puts `qty` in the sum reconciles it happily.
    """
    verdict = govern("net_mismatch_rejected", golden=gov_golden)
    assert checks_map(verdict)["net_reconciles"] is False

    fields = detail_fields(detail_for(verdict, "net_reconciles"))
    trap = proposals["net_mismatch_qty_factor"]
    assert money(fields.get("computed_net")) == pytest.approx(
        net_from_legs(trap), abs=CENT
    ), "the governor's own per-share sum must appear in the detail"
    assert money(fields.get("reported_net")) == pytest.approx(
        trap["net_debit_credit"], abs=CENT
    )

    # And the correctly-stated proposals reconcile.
    for case in ("debit_vertical_approved", "credit_vertical_approved",
                 "cash_secured_put_approved", "covered_call_approved"):
        assert checks_map(govern(case, golden=gov_golden))["net_reconciles"] is True


@requires_governor
def test_gb_c_05_risk_math_does_not_run_on_unreconciled_numbers(govern, gov_golden):
    """GB-C-05: a net that does not reconcile stops the risk band before it starts.

    The verdict still records every check — a rejection with a truncated
    `checks[]` is not an audit record — but the risk checks must say they were
    not evaluated rather than report a number computed from numbers the governor
    has just declared untrustworthy.
    """
    verdict = govern("net_mismatch_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert set(checks) >= set(CORE_RULES), "every check is still recorded"

    for rule in ("max_loss_cap", "coverage", "cash_floor"):
        assert checks[rule] is False, f"{rule} must fail closed, not pass unevaluated"
        detail = detail_for(verdict, rule)
        assert "not evaluated" in detail.lower(), (
            f"{rule} detail must say it was not evaluated, and why: {detail!r}"
        )
        assert "net_reconciles" in detail

    # The independent checks are unaffected by the gate.
    assert checks["market_open"] is True
    assert checks["churn_guard"] is True


@requires_governor
@pytest.mark.parametrize(
    "case_name, expected_max_loss",
    [
        ("cash_secured_put_approved", 61590.00),
        ("debit_vertical_approved", 430.00),
        ("credit_vertical_approved", 325.00),
        ("csp_over_cap_rejected", 62995.00),
        ("false_claim_rejected_by_computed_figure", 819.00),
    ],
)
def test_gb_c_06_governor_computes_max_loss_itself(
    govern, gov_golden, case_name, expected_max_loss
):
    """GB-C-06: max loss per structure, computed by the governor, in the detail.

    CSP        (strike - credit) * 100 * qty
    debit      debit * 100 * qty
    credit     (width - credit) * 100 * qty

    The figure must be visible in `checks[].detail`, not merely reflected in a
    pass/fail. A verdict that says only "passed": true is not an audit record.
    """
    verdict = govern(case_name, golden=gov_golden)
    fields = detail_fields(detail_for(verdict, "max_loss_cap"))
    assert money(fields.get("computed_max_loss")) == pytest.approx(
        expected_max_loss, abs=CENT
    )
    assert "cap" in fields, "the cap it was compared against belongs in the record"


@requires_governor
def test_gb_c_07_a_false_claim_does_not_govern(govern, gov_golden, proposals):
    """GB-C-07: THE false-claim fixture. The computed figure governs; the claim is evidence.

    `claimed_max_loss: 200` on a spread whose real max loss is 819, against a 500
    cap. A governor that trusts the claim approves it. The divergence must be
    surfaced in the detail — a claim that is wrong by 619 dollars is itself a
    finding worth putting on the ledger.
    """
    verdict = govern("false_claim_rejected_by_computed_figure", golden=gov_golden)
    liar = proposals["false_claim_debit_vertical"]

    assert checks_map(verdict)["max_loss_cap"] is False
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "max_loss_cap"))
    computed = money(fields.get("computed_max_loss"))
    assert computed == pytest.approx(819.00, abs=CENT)
    assert money(fields.get("cap")) == pytest.approx(500.00, abs=CENT)
    assert computed > liar["claimed_max_loss"], "fixture drift: the claim is not false"
    assert money(fields.get("claimed_max_loss")) == pytest.approx(
        liar["claimed_max_loss"], abs=CENT
    ), "the claim the governor diverged from belongs in the record (shape 3)"


@requires_governor
def test_gb_c_08_covered_call_coverage_cannot_be_double_claimed(govern, gov_golden):
    """GB-C-08: a covered call needs 100 * qty UNRESERVED shares.

    The account holds exactly 100 shares and has all 100 reserved against an open
    short call. Two covered calls cannot claim the same 100 shares; a governor
    that reads `shares` and ignores `reserved_shares` writes the second one.
    """
    verdict = govern("covered_call_double_claim_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["coverage"] is False
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "coverage"))
    assert money(fields.get("unreserved_shares")) == 0
    assert money(fields.get("required_shares")) == 100

    # And the same proposal against unreserved shares is approved.
    assert govern("covered_call_approved", golden=gov_golden)["approved"] is True


@requires_governor
def test_gb_c_09_cash_secured_put_needs_unreserved_cash(govern, gov_golden):
    """GB-C-09: a CSP needs strike * 100 * qty in UNRESERVED cash.

    62000 in cash looks sufficient until the 20000 already committed to another
    put is subtracted.
    """
    verdict = govern("csp_coverage_rejected", golden=gov_golden)
    assert checks_map(verdict)["coverage"] is False

    fields = detail_fields(detail_for(verdict, "coverage"))
    assert money(fields.get("unreserved_cash")) == pytest.approx(42000.00, abs=CENT)
    assert money(fields.get("required_cash")) == pytest.approx(62000.00, abs=CENT)


@requires_governor
def test_gb_c_10_vertical_needs_buying_power_for_the_computed_max_loss(
    govern, gov_golden
):
    """GB-C-10: a vertical's coverage is buying power against the COMPUTED max loss.

    Not against the claim, and not against the debit alone.
    """
    verdict = govern("vertical_buying_power_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["coverage"] is False
    assert checks["cash_floor"] is True, "cash floor still passes: coverage is isolated"

    fields = detail_fields(detail_for(verdict, "coverage"))
    assert money(fields.get("buying_power")) == pytest.approx(300.00, abs=CENT)
    assert money(fields.get("required_buying_power")) == pytest.approx(430.00, abs=CENT)


@requires_governor
def test_gb_c_11_cash_floor_is_a_separate_question_from_coverage(govern, gov_golden):
    """GB-C-11: post-trade free cash below the configured floor fails.

    The collateral is there (65000 against 62000 required) and the trade is still
    refused, because it would leave 3410 against a 13000 floor. Coverage passing
    is exactly what makes this case about cash_floor.
    """
    verdict = govern("cash_floor_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["coverage"] is True
    assert checks["cash_floor"] is False
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "cash_floor"))
    assert money(fields.get("cash_after")) == pytest.approx(3410.00, abs=CENT)
    assert money(fields.get("floor")) == pytest.approx(13000.00, abs=CENT)


@requires_governor
def test_gb_c_12_churn_guard_blocks_re_entry_inside_the_window(govern, gov_golden):
    """GB-C-12: a second open on the same underlying inside the window fails."""
    verdict = govern("churn_window_rejected", golden=gov_golden)
    assert checks_map(verdict)["churn_guard"] is False
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "churn_guard"))
    assert money(fields.get("seconds_since_last_open")) == pytest.approx(600, abs=1)
    assert money(fields.get("churn_window_seconds")) == pytest.approx(3600, abs=1)


@requires_governor
def test_gb_c_13_min_hold_is_not_the_churn_window(govern, gov_golden):
    """GB-C-13: the min hold binds where the churn window has already released.

    The position is 5400 s old: past the 3600 s churn window, short of the 7200 s
    min hold. A governor that collapses the two limits into one number lets this
    trade through.
    """
    verdict = govern("min_hold_rejected", golden=gov_golden)
    assert checks_map(verdict)["churn_guard"] is False

    fields = detail_fields(detail_for(verdict, "churn_guard"))
    assert money(fields.get("position_age_seconds")) == pytest.approx(5400, abs=1)
    assert money(fields.get("min_hold_seconds")) == pytest.approx(7200, abs=1)
    assert money(fields.get("seconds_since_last_open")) > money(
        fields.get("churn_window_seconds")
    ), "the churn window has released; only the min hold binds"


@requires_governor
def test_gb_c_14_closed_market_gates_submission_without_hiding_the_rest(
    govern, gov_golden
):
    """GB-C-14: market_open fails on a closed clock, and every other check is still run.

    6c: screening and proposing run at any time; submission is gated here. The
    verdict is the audit record for the whole decision, so an early exit that
    reported one failed check and nothing else would lose the reason the trade
    was worth making.
    """
    verdict = govern("market_closed_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["market_open"] is False
    assert verdict["approved"] is False

    for rule in ("structure_valid", "net_reconciles", "max_loss_cap", "coverage",
                 "cash_floor", "churn_guard"):
        assert checks[rule] is True, f"{rule} must still be evaluated on a closed clock"
    fields = detail_fields(detail_for(verdict, "max_loss_cap"))
    assert money(fields.get("computed_max_loss")) == pytest.approx(430.00, abs=CENT)


@requires_governor
def test_gb_c_15_non_seam_checks_ride_the_x_prefix(govern, gov_golden):
    """GB-C-15: position caps are not seam vocabulary, so the check is `x_position_cap`.

    3a is a hybrid: the core names are pinned and a rename needs both humans, but
    the governor lead may add checks under `x_` without a seam change. This is
    that escape hatch actually being used, and it must not smuggle a new name
    into the core vocabulary.
    """
    verdict = govern("position_cap_rejected", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["x_position_cap"] is False
    assert verdict["approved"] is False

    for rule in checks:
        assert rule in CORE_RULES or rule.startswith("x_"), (
            f"{rule} is neither pinned seam vocabulary nor an x_ extension"
        )

    fields = detail_fields(detail_for(verdict, "x_position_cap"))
    assert money(fields.get("open_for_underlying")) == 2
    assert money(fields.get("max_open_per_underlying")) == 2


@requires_governor
def test_gb_c_16_verdict_matches_seam_shape_3(govern, gov_golden, gov_config_version):
    """GB-C-16: the verdict envelope is shape 3, and every check is fully formed.

    `mode` passes through, `config_version` is the caller's, every check carries
    rule/passed/detail, and `prompt_version` is nowhere near it — the governor is
    deterministic and has no prompt, and a prompt version on its verdict would
    imply an LLM in the risk path.
    """
    for case_name in ("debit_vertical_approved", "false_claim_rejected_by_computed_figure"):
        case = gov_golden["cases"][case_name]
        verdict = govern(case_name, golden=gov_golden)

        assert verdict["mode"] == case["mode"]
        assert verdict["config_version"] == gov_config_version
        assert "prompt_version" not in verdict
        assert isinstance(verdict["reason"], str) and verdict["reason"].strip()
        assert isinstance(verdict["approved"], bool)

        for check in verdict["checks"]:
            assert set(check) >= {"rule", "passed", "detail"}, check
            assert isinstance(check["passed"], bool)
            assert isinstance(check["detail"], str) and check["detail"].strip(), (
                f"{check['rule']} has no detail; a bare pass/fail is not an audit record"
            )
        assert [c["rule"] for c in verdict["checks"]][:len(CORE_RULES)] == list(CORE_RULES), (
            "core checks appear in the seam's order, extensions after"
        )


@requires_governor
def test_gb_c_17_approved_only_when_every_check_passed(govern, gov_golden):
    """GB-C-17: `approved` is derived, never asserted independently."""
    for case_name in gov_golden["cases"]:
        verdict = govern(case_name, golden=gov_golden)
        checks = checks_map(verdict)
        assert verdict["approved"] is all(checks.values()), (
            f"{case_name}: approved={verdict['approved']} vs checks {checks}"
        )


@requires_governor
def test_gb_c_18_matches_golden_verdicts(govern, gov_golden):
    """GB-C-18: every case matches the golden file, check by check."""
    for case_name, case in gov_golden["cases"].items():
        verdict = govern(case_name, golden=gov_golden)
        checks = checks_map(verdict)
        assert checks == case["checks"], f"{case_name}: checks differ from golden"
        assert verdict["approved"] is case["approved"], f"{case_name}: approved differs"

        expected_max_loss = case["computed_max_loss"]
        got = money(detail_fields(detail_for(verdict, "max_loss_cap")).get("computed_max_loss"))
        if expected_max_loss is None:
            assert got is None, f"{case_name}: expected no computed max loss, got {got}"
        else:
            assert got == pytest.approx(expected_max_loss, abs=CENT), case_name


@requires_governor
def test_gb_c_19_is_deterministic_and_takes_its_config_from_the_caller(
    govern, gov_golden, proposals, account_states, clocks, gov_thresholds,
    gov_config_version
):
    """GB-C-19: identical inputs give identical verdicts; the caller owns the config.

    No clock, no randomness, no file I/O. The governor reads `as_of` from the
    clock it is handed and thresholds from the mapping it is handed, so two runs
    against the same inputs are the same verdict — which is what makes a ledger
    entry re-checkable months later.
    """
    first = govern("credit_vertical_approved", golden=gov_golden)
    second = govern("credit_vertical_approved", golden=gov_golden)
    assert first == second

    # A different config produces a different verdict from the same inputs, which
    # is the proof the threshold is not baked into the code.
    tightened = dict(gov_thresholds)
    tightened["max_loss_cap"] = dict(gov_thresholds["max_loss_cap"])
    tightened["max_loss_cap"]["vertical_spread"] = 100.00
    verdict = run_governor(
        proposals["credit_vertical_ok"], account_states["composed_flat"],
        clocks["open"], tightened, "approve", "sha256:tightened",
    )
    assert checks_map(verdict)["max_loss_cap"] is False
    assert verdict["config_version"] == "sha256:tightened"


@requires_governor
def test_gb_c_20_covered_call_risk_is_coverage_not_a_max_loss_cap(govern, gov_golden):
    """GB-C-20: a covered call has no standalone max-loss cap, and says so.

    Its downside is the share position it is written against, bounded by
    coverage (2e). The check must pass with an explanation rather than invent a
    number or quietly skip.
    """
    verdict = govern("covered_call_approved", golden=gov_golden)
    checks = checks_map(verdict)
    assert checks["max_loss_cap"] is True
    assert checks["coverage"] is True
    assert verdict["approved"] is True

    detail = detail_for(verdict, "max_loss_cap")
    assert "coverage" in detail.lower()
    assert money(detail_fields(detail).get("computed_max_loss")) is None


@requires_governor
def test_gb_c_21_raw_broker_state_is_a_caller_error(
    proposals, account_states, clocks, gov_thresholds, gov_config_version
):
    """GB-C-21: handing the governor the data layer's RAW state raises.

    A2 (b): reservations are governor-derived from the ledger and never come from
    the data layer. A governor that silently accepted a raw state would read
    every reservation as zero and approve every double-claim. That is a caller
    error, not a rejection: it raises rather than being laundered into a verdict
    that looks like a considered decision.
    """
    with pytest.raises(ValueError):
        run_governor(
            proposals["covered_call_ok"], account_states["raw_broker_state"],
            clocks["open"], gov_thresholds, "approve", gov_config_version,
        )
