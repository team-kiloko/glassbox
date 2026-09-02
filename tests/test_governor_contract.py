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


# ---------------------------------------------------------------------------
# GB-C-F07 and GB-C-22..24 — the scored-run expiry bound
#
# Added 2026-09-02 with the bound itself. The seam's pinned core vocabulary
# (3a) has NO home for an expiry rule: `structure_valid` is defined there as
# leg composition plus ratio_qty/GCD, and widening it to hold an unrelated rule
# would be a seam change made by not writing one down. So the check rides `x_`,
# which is the extension point 3a grants the governor lead — and GB-C-23 pins
# that it stays there.
# ---------------------------------------------------------------------------

def test_gb_c_f07_scored_config_is_complete_and_agrees_with_the_reference(
    scored_thresholds, gov_thresholds
):
    """GB-C-F07: the scored config is loadable, complete, and has not drifted.

    The scored bound is a DECIDED value that a real run loads on a scored
    account. A config nothing asserts against is a config that can drift to
    anything between now and Thursday.
    """
    assert scored_thresholds["max_expiry_date"] == "2026-09-03", (
        "DECIDED: scoring reads total account equity at EOD Thursday 2026-09-03, "
        "so a position must resolve on or before it to be scored as collected "
        "premium rather than at its mark"
    )
    assert "DECIDED" in scored_thresholds["_status"]
    assert scored_thresholds["_max_expiry_rationale"].strip(), (
        "a DECIDED number carries its reasoning in the file, or the reasoning is "
        "lost the moment the conversation that produced it ends"
    )

    # Every tunable the governor requires is present.
    for key in ("max_loss_cap", "net_reconcile_tolerance", "cash_floor_pct",
                "churn_window_seconds", "min_hold_seconds", "position_caps",
                "max_expiry_date"):
        assert key in scored_thresholds, f"scored config is missing {key}"

    # The known duplication, held still. Every number except the bound exists in
    # both files; this makes a drift a test failure rather than a discovery.
    shared = [k for k in gov_thresholds
              if not k.startswith("_") and k != "max_expiry_date"]
    assert shared, "nothing shared to compare"
    for key in shared:
        assert scored_thresholds[key] == gov_thresholds[key], (
            f"{key} has drifted between the scored config and the suite's "
            f"reference config. They are duplicated on purpose and must stay "
            f"identical until one calibrated config replaces both"
        )


@requires_governor
def test_gb_c_22_scored_bound_rejects_a_leg_that_outlives_it(
    govern, gov_golden, scored_thresholds, proposals
):
    """GB-C-22: under the SCORED config, a Sep 18 vertical is rejected.

    Run against the real scored config, not a fixture one. `credit_vertical_ok`
    is the golden APPROVED credit vertical — it passes every other check by
    construction — so under the scored bound the only thing that can change is
    the expiry, and it does.
    """
    approved_under_reference = govern("credit_vertical_approved", golden=gov_golden)
    assert approved_under_reference["approved"] is True, "sanity: the same proposal passes"

    verdict = govern(
        proposal="credit_vertical_ok", account="composed_flat", clock="open",
        thresholds=scored_thresholds,
    )
    checks = checks_map(verdict)
    assert checks["x_max_expiry"] is False
    assert verdict["approved"] is False

    # Isolated: nothing else moved, so the rejection is attributable.
    assert [rule for rule, passed in checks.items() if not passed] == ["x_max_expiry"]

    fields = detail_fields(detail_for(verdict, "x_max_expiry"))
    assert fields["max_expiry_date"] == "2026-09-03"
    assert fields["late_legs"] == "2", "both legs are past the bound, and both are named"
    assert "2026-09-18" in detail_for(verdict, "x_max_expiry"), (
        "the detail names what actually expires, not only the bound"
    )


@requires_governor
def test_gb_c_23_the_bound_is_an_extension_and_never_colonises_the_core(
    govern, scored_thresholds
):
    """GB-C-23: `structure_valid` is pinned seam vocabulary and stays untouched.

    The tempting shortcut is to fail a late expiry as `structure_valid` — it is
    already a rejection, and no new rule name appears. That would silently
    redefine a check the seam pins, the dashboard names, and both humans agreed
    on. The bound is an `x_` extension, and this test is what stops it drifting
    into the core.
    """
    verdict = govern(
        proposal="credit_vertical_ok", account="composed_flat", clock="open",
        thresholds=scored_thresholds,
    )
    checks = checks_map(verdict)
    assert checks["structure_valid"] is True, (
        "the structure is valid; only its expiry is out of bounds"
    )
    assert "x_max_expiry" not in CORE_RULES, (
        "the pinned core vocabulary is a seam change to alter (3a)"
    )
    assert [c["rule"] for c in verdict["checks"]][:len(CORE_RULES)] == list(CORE_RULES)
    assert all(rule in CORE_RULES or rule.startswith("x_") for rule in checks)


@requires_governor
def test_gb_c_24_no_bound_configured_passes_and_says_so(
    govern, scored_thresholds
):
    """GB-C-24: `null` is a stated fact, not a silent pass.

    A run that is not the scored one has no expiry bound, and the audit record
    must say that rather than showing a check that quietly passed for reasons
    nobody can reconstruct later.
    """
    unbounded = dict(scored_thresholds, max_expiry_date=None)
    verdict = govern(
        proposal="credit_vertical_ok", account="composed_flat", clock="open",
        thresholds=unbounded,
    )
    assert checks_map(verdict)["x_max_expiry"] is True
    detail = detail_for(verdict, "x_max_expiry")
    assert detail_fields(detail)["max_expiry_date"] == "null"
    assert "no scored-run expiry bound" in detail


# ---------------------------------------------------------------------------
# GB-C-F08 and GB-C-25..29 — percentage-of-equity caps, and the portfolio cap
#
# Added 2026-09-02 with the scored competition account. Two additions, one
# reason: a cap on a single trade is not a cap on the account, and a cap stated
# in dollars is an absolute claim about a number that moves.
#
#   * A cap may be `{"pct_of_equity": f}` as well as a number of dollars. The
#     governor resolves it against `equity` in its composed view, records the
#     resolved figure AND its basis, and fails closed when it cannot resolve it.
#     An unresolvable cap is not an absent one.
#   * `x_total_open_risk` sums the governor's own computed max loss across the
#     positions the ledger says are bearing risk, adds the proposal's, and
#     compares the total against a portfolio cap. Not seam vocabulary, so it
#     rides `x_` — the extension point 3a grants the governor lead.
#
# The golden exercises the dollar form (its 20 hand-authored verdicts did not
# need re-tuning to gain a check that passes in all of them). These exercise the
# percentage form, which is what the scored account actually runs on.
# ---------------------------------------------------------------------------

COMPETITION_CONFIG = "thresholds.competition.json"


@pytest.fixture(scope="session")
def competition_thresholds():
    import json
    from conftest import CONFIG_DIR

    with (CONFIG_DIR / COMPETITION_CONFIG).open() as fh:
        return json.load(fh)


def test_gb_c_f08_the_competition_config_is_complete_and_says_what_it_decided(
    competition_thresholds, gov_thresholds
):
    """GB-C-F08: the config a SCORED order is judged under, asserted rather than trusted.

    This file's content hash is the `config_version` on every decision made on
    the account whose closing equity is the judged number. A config nothing
    asserts against is a config that can drift to anything.
    """
    config = competition_thresholds

    # Every tunable the governor requires.
    for key in ("max_loss_cap", "net_reconcile_tolerance", "cash_floor_pct",
                "churn_window_seconds", "min_hold_seconds", "position_caps",
                "max_expiry_date"):
        assert key in config, f"competition config is missing {key}"

    assert config["max_expiry_date"] == "2026-09-03", (
        "every position this account takes must resolve inside the scored window"
    )

    # The three DECIDED numbers, and the fact that they are stated as fractions.
    assert config["max_loss_cap"]["covered_call"] is None, (
        "2e: a covered call has no standalone max-loss figure, and a percentage "
        "there would be a number invented to look like a limit"
    )
    for structure in ("cash_secured_put", "vertical_spread"):
        assert config["max_loss_cap"][structure] == {"pct_of_equity": 0.02}, structure
    assert config["x_total_open_risk"] == {"pct_of_equity": 0.10}

    # Each DECIDED number carries its reasoning in the file, or the reasoning is
    # lost the moment the conversation that produced it ends.
    for key in ("_sizing_rationale", "_max_expiry_rationale",
                "_x_total_open_risk_rationale"):
        assert config[key].strip(), f"{key} is empty"
    assert "teakeycee" in config["_sizing_rationale"], (
        "a sizing decision is a HUMAN's, and the file says whose"
    )
    assert "PROPOSED" in config["_status"], (
        "the sizing numbers are decided; the rest of the file is not calibrated "
        "and must not claim to be"
    )

    # Everything that is NOT one of the three decisions is inherited verbatim.
    # A run whose thresholds were quietly tuned to fit its own trades proves
    # nothing, so the drift is a test failure rather than a discovery.
    decided = {"max_loss_cap", "max_expiry_date", "x_total_open_risk"}
    inherited = [k for k in gov_thresholds
                 if not k.startswith("_") and k not in decided]
    assert inherited, "nothing shared to compare"
    for key in inherited:
        assert config[key] == gov_thresholds[key], (
            f"{key} has drifted from the suite's reference config. Only the three "
            f"DECIDED numbers may differ; the rest is inherited calibration"
        )

    # The liquidity window belongs to the harness's proposal helper, and is here
    # so config_version covers what the proposal was CHOSEN under as well as
    # what it was judged under.
    window = config["liquidity_window"]
    assert window["require_two_sided_quote"] is True
    assert window["min_open_interest"] == 500
    assert window["short_leg_abs_delta_min"] == 0.15
    assert window["short_leg_abs_delta_max"] == 0.35
    assert "PROPOSED" in window["_status"]


@requires_governor
def test_gb_c_25_a_cap_may_be_a_fraction_of_equity(govern, gov_thresholds,
                                                   account_states):
    """GB-C-25: `pct_of_equity` resolves against the composed view's equity.

    And the resolved figure is not the whole record: the check's detail must
    also say what it was a percentage OF, or a reader six weeks later cannot
    tell a 2,000.00 cap that was 2% of 100,000.00 from one that was typed in.
    """
    equity = account_states["composed_flat"]["equity"]
    generous = dict(gov_thresholds,
                    max_loss_cap=dict(gov_thresholds["max_loss_cap"],
                                      vertical_spread={"pct_of_equity": 0.02}))
    verdict = govern(proposal="credit_vertical_ok", account="composed_flat",
                     thresholds=generous)
    fields = detail_fields(detail_for(verdict, "max_loss_cap"))
    assert checks_map(verdict)["max_loss_cap"] is True
    assert money(fields["cap"]) == pytest.approx(0.02 * equity, abs=CENT)
    assert fields["cap_basis"] == "0.02_of_equity"
    assert money(fields["equity"]) == pytest.approx(equity, abs=CENT)
    assert money(fields["computed_max_loss"]) == pytest.approx(325.00, abs=CENT)

    # The same proposal, the same account, a tighter fraction: rejected on the
    # cap alone. The percentage is doing the work, not a coincidence.
    tight = dict(gov_thresholds,
                 max_loss_cap=dict(gov_thresholds["max_loss_cap"],
                                   vertical_spread={"pct_of_equity": 0.002}))
    verdict = govern(proposal="credit_vertical_ok", account="composed_flat",
                     thresholds=tight)
    checks = checks_map(verdict)
    assert checks["max_loss_cap"] is False
    assert [rule for rule, ok in checks.items() if not ok] == ["max_loss_cap"]
    assert money(detail_fields(detail_for(verdict, "max_loss_cap"))["cap"]) == (
        pytest.approx(0.002 * equity, abs=CENT)
    )


@requires_governor
def test_gb_c_26_an_unresolvable_percentage_cap_fails_closed(gov_thresholds,
                                                             account_states, clocks,
                                                             proposals,
                                                             gov_config_version):
    """GB-C-26: a percentage of an equity nobody supplied is a REFUSAL.

    The failure mode this exists for: a caller composes an account view without
    `equity`, every percentage cap silently resolves to nothing, and the run
    proceeds uncapped. An unresolvable cap is not an absent one.
    """
    account = {k: v for k, v in account_states["composed_flat"].items() if k != "equity"}
    assert "equity" not in account
    thresholds = dict(
        gov_thresholds,
        max_loss_cap=dict(gov_thresholds["max_loss_cap"],
                          vertical_spread={"pct_of_equity": 0.02}),
        x_total_open_risk={"pct_of_equity": 0.10},
    )
    verdict = run_governor(proposals["credit_vertical_ok"], account, clocks["open"],
                           thresholds, "approve", gov_config_version)
    checks = checks_map(verdict)
    assert checks["max_loss_cap"] is False
    assert checks["x_total_open_risk"] is False
    for rule in ("max_loss_cap", "x_total_open_risk"):
        detail = detail_for(verdict, rule)
        assert "equity=null" in detail, detail
        assert "fails closed" in detail or "failing closed" in detail, detail

    # A malformed cap is a different thing entirely: that is a broken config, a
    # caller error, and laundering it into a rejection would dress a bug up as a
    # considered decision.
    for broken in ({"pct_of_equity": 0}, {"pct_of_equity": "2%"}, "500.00", []):
        with pytest.raises(ValueError):
            run_governor(
                proposals["credit_vertical_ok"], account_states["composed_flat"],
                clocks["open"],
                dict(gov_thresholds,
                     max_loss_cap=dict(gov_thresholds["max_loss_cap"],
                                       vertical_spread=broken)),
                "approve", gov_config_version,
            )


@requires_governor
def test_gb_c_27_the_portfolio_cap_counts_the_book_not_the_trade(govern,
                                                                 gov_thresholds,
                                                                 account_states):
    """GB-C-27: every per-trade check passes and the trade is still refused.

    The whole argument for the check, in one case: four trades each inside their
    own cap reach the same place one oversized trade would.
    """
    verdict = govern(proposal="credit_vertical_ok",
                     account="composed_open_risk_saturated")
    checks = checks_map(verdict)
    assert [rule for rule, ok in checks.items() if not ok] == ["x_total_open_risk"]
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "x_total_open_risk"))
    already = account_states["composed_open_risk_saturated"]["ledger"]["open_risk"]["total"]
    assert money(fields["open_risk_before"]) == pytest.approx(already, abs=CENT)
    assert money(fields["proposed_max_loss"]) == pytest.approx(325.00, abs=CENT)
    assert money(fields["total_open_risk"]) == pytest.approx(already + 325.00, abs=CENT)
    assert money(fields["cap"]) == pytest.approx(gov_thresholds["x_total_open_risk"],
                                                 abs=CENT)

    # The same book, as a fraction of equity instead of dollars, and 1% of
    # 100,000.00 is far under what is already open: still refused, and the
    # detail says what the cap was a fraction of.
    verdict = govern(proposal="credit_vertical_ok",
                     account="composed_open_risk_saturated",
                     thresholds=dict(gov_thresholds,
                                     x_total_open_risk={"pct_of_equity": 0.01}))
    fields = detail_fields(detail_for(verdict, "x_total_open_risk"))
    assert checks_map(verdict)["x_total_open_risk"] is False
    assert fields["cap_basis"] == "0.01_of_equity"
    assert money(fields["cap"]) == pytest.approx(1000.00, abs=CENT)


@requires_governor
def test_gb_c_28_an_unknown_book_is_never_an_empty_one(gov_thresholds, proposals,
                                                       account_states, clocks,
                                                       gov_config_version):
    """GB-C-28: no ledger-derived open_risk means the check FAILS, not passes.

    "I do not know what is already on the book" must never resolve to "nothing
    is". This is the same fail-closed discipline `churn_guard` and
    `x_position_cap` hold, applied to the figure that bounds the account.
    """
    base = account_states["composed_flat"]
    for ledger in ({"open_positions": {}, "recent_activity": {}},
                   {"open_positions": {}, "recent_activity": {}, "open_risk": {}},
                   {"open_positions": {}, "recent_activity": {},
                    "open_risk": {"total": None}}):
        account = dict(base, ledger=ledger)
        verdict = run_governor(proposals["credit_vertical_ok"], account,
                               clocks["open"], gov_thresholds, "approve",
                               gov_config_version)
        assert checks_map(verdict)["x_total_open_risk"] is False, ledger
        assert "failing closed" in detail_for(verdict, "x_total_open_risk")

    # And with no cap configured at all, the check passes and SAYS it is unbounded
    # rather than passing silently — the same shape as x_max_expiry's null bound.
    unconfigured = {k: v for k, v in gov_thresholds.items() if k != "x_total_open_risk"}
    verdict = run_governor(proposals["credit_vertical_ok"], base, clocks["open"],
                           unconfigured, "approve", gov_config_version)
    assert checks_map(verdict)["x_total_open_risk"] is True
    assert "x_total_open_risk=null" in detail_for(verdict, "x_total_open_risk")


@requires_governor
def test_gb_c_29_the_extensions_stay_extensions_and_the_arithmetic_is_public(
    govern, gov_golden
):
    """GB-C-29: `x_total_open_risk` rides `x_`, and composers get the real function.

    The core vocabulary is pinned by the seam and closed to this pod (3a). The
    check is also only as good as the figure handed to it, so the arithmetic a
    composer must use to build that figure is exported rather than reimplemented
    at the call site — a second copy of the max-loss formula is exactly how an
    aggregate ends up disagreeing with the checks it aggregates.
    """
    verdict = govern("credit_vertical_approved", golden=gov_golden)
    rules = [c["rule"] for c in verdict["checks"]]
    assert rules[:len(CORE_RULES)] == list(CORE_RULES), (
        "core checks in seam order, extensions after"
    )
    assert "x_total_open_risk" in rules[len(CORE_RULES):]
    assert set(CORE_RULES).isdisjoint({"x_total_open_risk"}), (
        "adding a rule to the pinned core vocabulary is a seam change"
    )

    from conftest import GOVERNOR

    assert GOVERNOR.computed_max_loss({
        "structure": "vertical_spread", "qty": 2,
        "legs": [{"action": "sell", "strike": 635.0, "limit_price": 6.30, "ratio_qty": 1},
                 {"action": "buy", "strike": 630.0, "limit_price": 4.55, "ratio_qty": 1}],
    }) == pytest.approx(650.00, abs=CENT), "width minus credit, times 100, times qty"
    assert GOVERNOR.computed_max_loss({
        "structure": "covered_call", "qty": 1,
        "legs": [{"action": "sell", "strike": 660.0, "limit_price": 3.10, "ratio_qty": 1}],
    }) is None, "2e: no standalone figure, and none is invented for an aggregate"
    assert GOVERNOR.computed_max_loss({"structure": "vertical_spread", "qty": 1,
                                       "legs": [{"action": "sideways"}]}) is None, (
        "a proposal whose legs will not reconcile yields no figure, not a wrong one"
    )


# ---------------------------------------------------------------------------
# GB-C-F09 and GB-C-30..34 — the composed account view, promoted (A2 b)
#
# The composition of the account view the governor is handed is part of what
# every ledger-derived check MEANS, and it lived in `scripts/dry_run.py` until
# 2026-09-02. That is not a filing question. On 2026-09-02 the harness composed
# `recent_activity` over the chains that were still IN FLIGHT; a filled chain is
# terminal as an ORDER; and so `churn_guard` — a check whose entire job is to
# stop a second position going on the same underlying too soon — could not see
# the position that had just been opened. Two scored orders went on SPY 55
# seconds apart, both correctly approved by every check as the checks were
# written, and the guard that should have refused the second one passed with
# `seconds_since_last_open=null`.
#
# The fixture is that day's ledger, byte for byte. These criteria are the fix.
# ---------------------------------------------------------------------------

CHURN_CASE_ROOT_1 = "20260902T150903Z-973c931c1d"
CHURN_CASE_ROOT_2 = "20260902T150958Z-fe8c507ed1"


def _root(entries, root_id):
    for entry in entries:
        if entry["id"] == root_id:
            return entry
    raise AssertionError(f"no entry {root_id!r} in the churn-case fixture")


def _before(entries, root_id):
    """Every entry the ledger held when `root_id` was decided."""
    cut = _root(entries, root_id)["ts"]
    return [entry for entry in entries if entry["ts"] < cut]


def _closing_follow_up(entries, root_id, status, ts):
    """A closing transition appended to a chain, as the executor would write it.

    Built from the chain's own last entry so every provenance field rides the
    chain rather than being restated here (5a).
    """
    from conftest import ENTRY_FIELDS

    last = [e for e in entries if (e["root_id"] or e["id"]) == root_id][-1]
    entry = {field: last[field] for field in ENTRY_FIELDS}
    entry.update({"id": f"{root_id}+99-{status}", "root_id": root_id, "ts": ts,
                  "status": status, "snapshot": None, "proposal": None,
                  "verdict": None, "order": last["order"], "fill": None})
    return entries + [entry]


def test_gb_c_f09_the_churn_case_fixture_is_the_day_it_claims_to_be(
    churn_case_entries, competition_thresholds
):
    """GB-C-F09: the fixture is 2026-09-02's real pair of orders, unaltered.

    Everything below is an argument about a specific thing that happened. If the
    fixture stops being that thing, the argument is about nothing.
    """
    import hashlib
    from pathlib import Path

    entries = churn_case_entries
    root_1, root_2 = _root(entries, CHURN_CASE_ROOT_1), _root(entries, CHURN_CASE_ROOT_2)

    # Same underlying, same structure, 55 seconds apart.
    assert root_1["proposal"]["underlying"] == root_2["proposal"]["underlying"] == "SPY"
    assert root_1["proposal"]["structure"] == root_2["proposal"]["structure"]
    gap = (_parse(root_2["ts"]) - _parse(root_1["ts"])).total_seconds()
    assert 54 < gap < 56, f"the case is 55 seconds apart, this fixture is {gap:.1f}"
    assert gap < competition_thresholds["churn_window_seconds"], (
        "the whole case is that the gap sits INSIDE the churn window"
    )

    # The first chain had already FILLED — terminal as an order — when the
    # second decision was taken.
    from conftest import LEDGER

    before = _before(entries, CHURN_CASE_ROOT_2)
    status, terminal = LEDGER.current_status(before, CHURN_CASE_ROOT_1)
    assert (status, terminal) == ("filled", True)

    # And here is the defect, recorded in the entry's own verdict: the guard
    # passed, and its detail says why — it could not see anything at all.
    churn = [c for c in root_2["verdict"]["checks"] if c["rule"] == "churn_guard"][0]
    assert churn["passed"] is True
    assert "seconds_since_last_open=null" in churn["detail"]
    assert root_2["verdict"]["approved"] is True
    # while the SAME view already counted the position for the checks composed
    # over the risk-bearing set. One ledger, two answers.
    recorded_view = root_2["snapshot"]["account_state"]
    assert recorded_view["ledger"]["open_positions"] == {"SPY": 1}
    assert recorded_view["ledger"]["recent_activity"] == {}

    # The decisions were made under the scored config, and that config has not
    # moved since: a verdict names the numbers it was made under.
    digest = "sha256:" + hashlib.sha256(
        (Path(__file__).parent.parent / "config" / "thresholds.competition.json")
        .read_bytes()
    ).hexdigest()
    assert root_2["config_version"] == digest


@requires_governor
def test_gb_c_30_the_composed_view_belongs_to_the_governor(churn_case_entries):
    """GB-C-30: the composition is the governor's, and it now sees the position.

    Re-composing the second decision's own inputs must reproduce the view that
    was recorded that day in every respect but one — the one that was wrong.
    """
    from conftest import GOVERNOR, raw_of

    assert hasattr(GOVERNOR, "compose_account_view"), (
        "A2 (b) assigns the composed account view to the governor; a harness that "
        "composes it decides what the checks mean"
    )
    assert GOVERNOR.RISK_BEARING == frozenset(
        {"approved_pending", "submitted", "partial_fill", "filled"}
    ), "a filled chain is terminal as an order and open as a position"

    entries = churn_case_entries
    recorded = _root(entries, CHURN_CASE_ROOT_2)["snapshot"]["account_state"]
    view = GOVERNOR.compose_account_view(
        raw_of(recorded), _before(entries, CHURN_CASE_ROOT_2), recorded["equity"]
    )

    # Everything the composer already got right is untouched, to the cent.
    assert view["ledger"]["open_positions"] == recorded["ledger"]["open_positions"]
    assert view["ledger"]["open_risk"] == recorded["ledger"]["open_risk"]
    assert view["reserved_cash"] == recorded["reserved_cash"]
    assert view["positions"] == recorded["positions"]
    assert view["equity"] == recorded["equity"]
    assert {k: v for k, v in view.items() if k != "ledger"} == {
        k: v for k, v in recorded.items() if k != "ledger"
    }

    # And the one thing it got wrong is now right: the filled chain holds the
    # underlying open, anchored on the ROOT entry's ts (5a writes it first, so
    # it is the one timestamp every risk-bearing chain has).
    assert recorded["ledger"]["recent_activity"] == {}, "what was recorded"
    opened = _root(entries, CHURN_CASE_ROOT_1)["ts"]
    assert view["ledger"]["recent_activity"] == {
        "SPY": {"last_open_at": opened, "position_opened_at": opened}
    }


@requires_governor
def test_gb_c_31_a_filled_position_blocks_the_next_one_55_seconds_later(
    churn_case_entries, competition_thresholds
):
    """GB-C-31: THE CASE. The second scored order must fail `churn_guard`.

    Same proposal, same account, same clock, same config as the real decision —
    only the composition of the view is fixed. The verdict must flip, and it
    must flip on exactly one check: a fix that changed any other answer would be
    a different change, and the record of what the other checks said that day
    would stop meaning what it says.
    """
    from conftest import GOVERNOR, raw_of, run_governor

    entries = churn_case_entries
    second = _root(entries, CHURN_CASE_ROOT_2)
    recorded = second["snapshot"]["account_state"]
    view = GOVERNOR.compose_account_view(
        raw_of(recorded), _before(entries, CHURN_CASE_ROOT_2), recorded["equity"]
    )
    verdict = run_governor(
        second["proposal"], view, second["snapshot"]["clock"],
        competition_thresholds, second["mode"], second["config_version"],
    )

    checks = checks_map(verdict)
    assert checks["churn_guard"] is False
    assert verdict["approved"] is False

    fields = detail_fields(detail_for(verdict, "churn_guard"))
    assert fields["underlying"] == "SPY"
    assert fields["seconds_since_last_open"] == "55", (
        "the guard must be able to say how long ago, not 'null'"
    )
    assert int(fields["churn_window_seconds"]) == \
        competition_thresholds["churn_window_seconds"]
    assert "re-entry on this underlying inside the churn window" in \
        detail_for(verdict, "churn_guard")

    # Exactly one check moved, and it is the one this is about.
    recorded_checks = {c["rule"]: c["passed"] for c in second["verdict"]["checks"]}
    flipped = {rule for rule, passed in checks.items()
               if recorded_checks.get(rule) != passed}
    assert flipped == {"churn_guard"}, (
        f"the fix must change churn_guard and nothing else; it changed {flipped}"
    )


@requires_governor
def test_gb_c_32_a_closing_follow_up_is_what_releases_an_underlying(
    churn_case_entries, competition_thresholds
):
    """GB-C-32: the position is held open until a CLOSING follow-up says otherwise.

    "Filled counts as open" would be a trap if nothing could ever clear it — the
    guard would harden into a permanent ban on an underlying. What clears it is
    the same thing that clears it in reality: an entry saying the position is
    gone. Not the passage of a status, and never the absence of information.
    """
    from conftest import GOVERNOR, raw_of, run_governor

    entries = churn_case_entries
    second = _root(entries, CHURN_CASE_ROOT_2)
    recorded = second["snapshot"]["account_state"]
    before = _before(entries, CHURN_CASE_ROOT_2)

    for closing in ("canceled", "expired"):
        closed = _closing_follow_up(before, CHURN_CASE_ROOT_1, closing,
                                    "2026-09-02T15:09:30.000000Z")
        view = GOVERNOR.compose_account_view(raw_of(recorded), closed,
                                             recorded["equity"])
        assert view["ledger"]["recent_activity"] == {}, closing
        assert view["ledger"]["open_positions"] == {}, closing
        assert view["ledger"]["open_risk"]["total"] == 0.0, closing

        verdict = run_governor(
            second["proposal"], view, second["snapshot"]["clock"],
            competition_thresholds, second["mode"], second["config_version"],
        )
        assert checks_map(verdict)["churn_guard"] is True, closing

    # A `partial_fill` follow-up is NOT a closing one: it is not terminal, the
    # position is real, and it goes on holding the underlying.
    partial = _closing_follow_up(before, CHURN_CASE_ROOT_1, "partial_fill",
                                 "2026-09-02T15:09:30.000000Z")
    view = GOVERNOR.compose_account_view(raw_of(recorded), partial,
                                         recorded["equity"])
    assert set(view["ledger"]["recent_activity"]) == {"SPY"}
    assert view["ledger"]["open_positions"] == {"SPY": 1}


@requires_governor
def test_gb_c_33_reservations_still_read_the_in_flight_set_only(churn_case_entries):
    """GB-C-33: what the fix did NOT change — collateral is reserved once.

    The three questions the view answers have three different answers, and only
    one of them moved. A filled cash-secured put has already paid its collateral
    to the broker, and the raw `cash` the view is built on reflects that;
    reserving against it again would charge the account twice for one position.
    """
    from conftest import GOVERNOR, raw_of

    entries = churn_case_entries
    recorded = _root(entries, CHURN_CASE_ROOT_2)["snapshot"]["account_state"]
    raw = raw_of(recorded)

    csp_root = dict(
        _root(entries, CHURN_CASE_ROOT_1),
        id="csp-root", root_id=None, ts="2026-09-02T15:00:00.000000Z",
        proposal={"underlying": "QQQ", "structure": "cash_secured_put", "qty": 1,
                  "legs": [{"symbol": "QQQ260903P00500000", "action": "sell",
                            "option_type": "put", "strike": 500.0,
                            "expiry": "2026-09-03", "ratio_qty": 1,
                            "limit_price": 1.00}],
                  "net_debit_credit": -1.00, "rationale": "GB-C-33 fixture",
                  "claimed_max_loss": 49900.0, "claimed_max_gain": 100.0},
    )

    in_flight = GOVERNOR.compose_account_view(raw, [csp_root], recorded["equity"])
    assert in_flight["reserved_cash"] == 50000.0, (
        "an approved, unsubmitted CSP still commits its collateral"
    )

    filled = _closing_follow_up([csp_root], "csp-root", "filled",
                                "2026-09-02T15:00:05.000000Z")
    view = GOVERNOR.compose_account_view(raw, filled, recorded["equity"])
    assert view["reserved_cash"] == 0.0, (
        "a filled CSP has spent its collateral; reserving it again double-counts"
    )
    # It is still a position, though, on every question about the book.
    assert view["ledger"]["open_positions"] == {"QQQ": 1}
    assert set(view["ledger"]["recent_activity"]) == {"QQQ"}


@requires_governor
def test_gb_c_34_a_chain_that_never_opened_anything_holds_nothing(churn_case_entries):
    """GB-C-34: a refusal is not a position, and never blocks the next proposal.

    The fixture carries a `governor_rejected` root at the same timestamp as each
    approved one — the adversarial half of each run. Counting those would make
    every rejection block the underlying for an hour, which is the mirror-image
    defect of the one being fixed.
    """
    from conftest import GOVERNOR, raw_of

    entries = churn_case_entries
    recorded = _root(entries, CHURN_CASE_ROOT_2)["snapshot"]["account_state"]
    rejected = [e for e in _before(entries, CHURN_CASE_ROOT_2)
                if e["root_id"] is None and e["status"] == "governor_rejected"]
    assert rejected, "the fixture should carry the rejected half of the run"

    view = GOVERNOR.compose_account_view(raw_of(recorded), rejected,
                                         recorded["equity"])
    assert view["ledger"] == {
        "open_positions": {}, "recent_activity": {},
        "open_risk": {"total": 0.0, "counted_positions": 0, "unpriced_positions": 0},
    }
