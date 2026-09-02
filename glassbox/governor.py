"""Governor — GB_INTERFACES.md shape 3.

The only component that may emit an order, and the last thing standing between a
language model's opinion and a real position. Everything upstream of here is
advisory; everything downstream trusts the verdict.

Four properties it holds, in the order they matter:

1. **It computes max loss itself.** `claimed_max_loss` on the proposal is
   ADVISORY (2d) and is never an input to a decision. It is read only so the
   divergence between what the strategist claimed and what the arithmetic says
   can be put on the record.
2. **A naked short is unapprovable.** The declared `structure` must match the
   actual leg composition, and coverage is checked against account state, not
   against the schema. A covered call and a naked call are the same `legs[]`;
   only the shares behind them differ (2e).
3. **It is deterministic.** No clock, no randomness, no file I/O. `as_of` comes
   from the clock it is handed, thresholds from the mapping it is handed. Two
   runs on the same inputs give the same verdict, which is what makes a ledger
   entry re-checkable months later.
4. **The verdict is an audit record.** Every check appears in `checks[]` with the
   numbers the decision turned on in its `detail`, including on the checks that
   passed and on a rejection. A verdict that says only `"passed": true` answers
   nothing six weeks later.

Details use the seam's own `key=value` convention (shape 3's example is
`computed_max_loss=250.00 vs cap=500.00`): key=value tokens with prose between
them, readable by a human and parseable by the dashboard.

Two arithmetic definitions the seam names but does not pin — `cash_floor` and
`churn_guard` — are the governor lead's, marked PROPOSED, and written up in
`tests/fixtures/governor/README.md` where the other pod can attack them.

**Caps may be stated as a fraction of equity** (2026-09-02, for the scored run).
A dollar cap is an absolute belief about a number that moves; "2% of equity" is
the belief a human actually holds, and stating it directly means the config does
not silently become wrong as the account's equity changes. Both forms are
accepted — a number is dollars, `{"pct_of_equity": 0.02}` is resolved against
`equity` in the composed account view — and the resolved figure, its basis and
the equity it came from all land in the check's `detail`, so the record shows
what the cap WAS at the moment of the decision. A percentage cap with no equity
to resolve against **fails closed**: an unresolvable cap is not an absent one.

**`x_total_open_risk` (PROPOSED, 3a extension).** Per-structure caps bound one
trade; nothing bounded the book. This check sums the governor's own computed max
loss across every ledger position that is bearing risk, adds the proposal's, and
compares the total against a portfolio cap. It is not seam vocabulary, so it
rides `x_` exactly as `x_position_cap` and `x_max_expiry` do. The open figure is
ledger-derived and supplied by the composer; if it is absent the check fails
closed, because "I do not know what is already on the book" must never resolve to
"nothing is".

As in the screener, **data quality is rejected and a schema violation raises**: a
proposal whose numbers do not reconcile earns a verdict, while a caller who hands
over the data layer's raw account state where the governor's composed view
belongs gets an exception. The second is a bug, and laundering a bug into a
verdict that looks like a considered decision is worse than stopping.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

__all__ = ["govern", "CORE_RULES", "STRUCTURE_ENUM", "computed_max_loss"]

#: The pinned core checks[] vocabulary (GB_INTERFACES.md 3a), in seam order.
#: Renaming or removing one of these requires both humans. Extra checks this
#: module adds ride an `x_` prefix and go after the core ones.
CORE_RULES = (
    "structure_valid",
    "net_reconciles",
    "max_loss_cap",
    "coverage",
    "cash_floor",
    "churn_guard",
    "market_open",
)

#: The closed structure enum (2a). `iron_condor` is deliberately absent: a condor
#: is two composed verticals and never crosses the seam as one structure (A1 B).
STRUCTURE_ENUM = ("covered_call", "cash_secured_put", "vertical_spread")

#: The two checks the risk band depends on. If either fails, max_loss_cap,
#: coverage and cash_floor are not evaluated: risk math run on numbers the
#: governor has just declared untrustworthy is worse than no number at all.
_GATES = ("structure_valid", "net_reconciles")
_RISK_BAND = ("max_loss_cap", "coverage", "cash_floor")

_CONTRACT_MULTIPLIER = 100

_REQUIRED_THRESHOLDS = (
    "max_loss_cap",
    "net_reconcile_tolerance",
    "cash_floor_pct",
    "churn_window_seconds",
    "min_hold_seconds",
    "position_caps",
    "max_expiry_date",
)


def govern(proposal, account_state, clock_or_as_of, thresholds, mode, config_version):
    """Rule on one proposal. See module docstring and GB_INTERFACES.md shape 3.

    Args:
        proposal: strategy proposal, shape 2.
        account_state: the governor's COMPOSED account view, shape 2b — raw
            broker state plus ledger-derived reservations and activity. The data
            layer's raw output is not accepted here (A2 b).
        clock_or_as_of: a ``/v2/clock`` mapping (``timestamp`` + ``is_open``), or
            a timezone-aware ``datetime``. A bare datetime carries no market
            state, so ``market_open`` fails closed.
        thresholds: mapping of tunables, loaded and passed in by the caller.
        mode: ``approve`` or ``autopilot``.
        config_version: content hash of the config that produced this verdict.

    Returns:
        ``{"approved", "mode", "config_version", "checks": [...], "reason"}``
    """
    _validate_call(thresholds, mode, config_version)
    as_of, is_open = _read_clock(clock_or_as_of)
    account = _composed_account(account_state)

    checks = []

    structure_valid, structure_detail = _check_structure(proposal)
    checks.append(_check("structure_valid", structure_valid, structure_detail))

    net_ok, net_detail, computed_net = _check_net(proposal, thresholds)
    checks.append(_check("net_reconciles", net_ok, net_detail))

    gate_failed = next(
        (name for name, ok in (("structure_valid", structure_valid),
                               ("net_reconciles", net_ok)) if not ok),
        None,
    )

    if gate_failed is not None:
        for rule in _RISK_BAND:
            checks.append(_check(
                rule, False,
                f"not evaluated: {gate_failed} failed — risk math does not run on "
                f"a proposal whose structure or arithmetic is not trustworthy",
            ))
        # The portfolio check is risk-band arithmetic too: it needs this
        # proposal's max loss, which the gate has just said cannot be trusted.
        # It is appended after the x_ extensions below, so it is built here and
        # held rather than appended out of order.
        open_risk_check = _check(
            "x_total_open_risk", False,
            f"not evaluated: {gate_failed} failed — the book's total risk cannot "
            f"be extended by a figure the governor has declared untrustworthy",
        )
    else:
        max_loss = _computed_max_loss(proposal, computed_net)
        checks.append(_check(*_check_max_loss_cap(proposal, max_loss, account, thresholds)))
        checks.append(_check(*_check_coverage(proposal, account, max_loss, computed_net)))
        checks.append(_check(*_check_cash_floor(proposal, account, computed_net, thresholds)))
        open_risk_check = _check(
            *_check_total_open_risk(proposal, account, max_loss, thresholds)
        )

    checks.append(_check(*_check_churn(proposal, account, as_of, thresholds)))
    checks.append(_check(*_check_market_open(is_open)))
    checks.append(_check(*_check_position_cap(proposal, account, thresholds)))
    checks.append(_check(*_check_max_expiry(proposal, thresholds)))
    checks.append(open_risk_check)

    approved = all(check["passed"] for check in checks)
    return {
        "approved": approved,
        "mode": mode,
        "config_version": config_version,
        "checks": checks,
        "reason": _reason(approved, checks),
    }


def computed_max_loss(proposal):
    """The governor's own max-loss figure for a proposal, in dollars.

    Public so that a composer building the ledger-derived `open_risk` block uses
    THIS arithmetic on every position it counts, rather than trusting a figure
    recorded next to the position or — worse — a strategist's claim. Derives the
    net from the legs itself for the same reason.

    Returns None for a covered call, which has no standalone max-loss figure
    (2e), and None for a proposal whose legs will not reconcile into a net.
    """
    try:
        net = _net_from_legs(proposal)
    except ValueError:
        return None
    try:
        return _computed_max_loss(proposal, net)
    except (KeyError, TypeError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Call validation — caller errors raise, they do not become verdicts
# ---------------------------------------------------------------------------

def _validate_call(thresholds, mode, config_version):
    missing = [key for key in _REQUIRED_THRESHOLDS if key not in thresholds]
    if missing:
        raise ValueError(
            "thresholds is missing required key(s): " + ", ".join(missing)
            + " — the caller loads the config and passes it in whole; this module "
            "has no defaults"
        )
    if mode not in ("approve", "autopilot"):
        raise ValueError(f"mode must be 'approve' or 'autopilot', got {mode!r}")
    if not isinstance(config_version, str) or not config_version:
        raise ValueError(
            "config_version must be a non-empty string identifying the config that "
            "produced this verdict (shape 3)"
        )


def _read_clock(clock_or_as_of):
    """Return (as_of, is_open). A bare datetime knows no market state."""
    if isinstance(clock_or_as_of, datetime):
        if clock_or_as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return clock_or_as_of, None
    if isinstance(clock_or_as_of, dict):
        as_of = _parse_ts(clock_or_as_of.get("timestamp"))
        if as_of is None:
            raise ValueError("clock has no parseable 'timestamp'")
        is_open = clock_or_as_of.get("is_open")
        if not isinstance(is_open, bool):
            raise ValueError("clock 'is_open' must be a boolean")
        return as_of, is_open
    raise ValueError("clock_or_as_of must be a /v2/clock mapping or an aware datetime")


def _composed_account(account_state):
    """Require the governor's COMPOSED view, never the data layer's raw state."""
    if not isinstance(account_state, dict):
        raise ValueError("account_state must be a mapping (shape 2b)")
    for key in ("cash", "buying_power", "positions"):
        if key not in account_state:
            raise ValueError(f"account_state is missing {key} (shape 2b)")
    if "reserved_cash" not in account_state:
        raise ValueError(
            "account_state has no 'reserved_cash': this is the data layer's RAW "
            "broker state, not the governor's composed view. Reservations are "
            "derived from the ledger by the governor (A2 b); reading a raw state "
            "here would treat every reservation as zero"
        )
    for underlying, position in account_state["positions"].items():
        if "reserved_shares" not in position:
            raise ValueError(
                f"positions[{underlying}] has no 'reserved_shares': raw broker "
                "state where the composed view belongs (A2 b)"
            )
    # `equity` is PROPOSED and deliberately NOT required: only a percentage cap
    # needs it, and that path fails closed on its own with a detail saying why.
    # Requiring it here would turn a config choice into a caller error for every
    # existing caller that states its caps in dollars.
    return account_state


# ---------------------------------------------------------------------------
# structure_valid
# ---------------------------------------------------------------------------

def _check_structure(proposal):
    structure = proposal.get("structure")
    qty = proposal.get("qty")
    legs = proposal.get("legs") or []

    if structure not in STRUCTURE_ENUM:
        return False, (
            f"structure={structure!r} is outside the closed enum "
            f"({'|'.join(STRUCTURE_ENUM)}); an iron condor is two composed "
            f"vertical_spread proposals and never crosses the seam as one structure"
        )
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        return False, f"qty={qty!r} must be a positive integer at proposal level"

    ratios = [leg.get("ratio_qty") for leg in legs]
    if not legs or any(
        not isinstance(r, int) or isinstance(r, bool) or r < 1 for r in ratios
    ):
        return False, f"ratio_qty={ratios!r} must be positive integers on every leg"
    gcd = 0
    for ratio in ratios:
        gcd = math.gcd(gcd, ratio)
    if gcd != 1:
        return False, (
            f"structure={structure} ratio_gcd={gcd} legs={len(legs)} — leg ratios "
            f"must be in simplest form, GCD 1 (C2)"
        )

    shorts = [leg for leg in legs if leg.get("action") == "sell"]
    longs = [leg for leg in legs if leg.get("action") == "buy"]

    if structure == "covered_call":
        if len(legs) != 1 or len(shorts) != 1 or legs[0].get("option_type") != "call":
            return False, (
                f"structure=covered_call legs={len(legs)} shorts={len(shorts)} — a "
                f"covered call is exactly one short call leg"
            )
    elif structure == "cash_secured_put":
        if len(legs) != 1 or len(shorts) != 1 or legs[0].get("option_type") != "put":
            return False, (
                f"structure=cash_secured_put legs={len(legs)} shorts={len(shorts)} — "
                f"a cash-secured put is exactly one short put leg"
            )
    else:  # vertical_spread
        if len(legs) != 2 or len(shorts) != 1 or len(longs) != 1:
            return False, (
                f"structure=vertical_spread legs={len(legs)} longs={len(longs)} "
                f"shorts={len(shorts)} — a vertical is one long and one short leg; "
                f"a lone short leg is a naked short wearing a defined-risk label (2e)"
            )
        if longs[0].get("option_type") != shorts[0].get("option_type"):
            return False, "structure=vertical_spread — both legs must be the same option_type"
        if longs[0].get("expiry") != shorts[0].get("expiry"):
            return False, "structure=vertical_spread — both legs must share an expiry"
        if longs[0].get("strike") == shorts[0].get("strike"):
            return False, "structure=vertical_spread — the legs must have different strikes"

    return True, (
        f"structure={structure} legs={len(legs)} qty={qty} ratio_gcd=1 — declared "
        f"structure matches leg composition"
    )


# ---------------------------------------------------------------------------
# net_reconciles
# ---------------------------------------------------------------------------

def _net_from_legs(proposal):
    """C1: sum(sign(action) * limit_price * ratio_qty), buys positive.

    Per share, for ONE unit of the spread. `qty` is NOT a factor and must not
    appear in this sum: the wire limit is per unit and independent of qty.
    """
    total = 0.0
    for leg in proposal.get("legs") or []:
        action = leg.get("action")
        if action not in ("buy", "sell"):
            raise ValueError(f"leg action must be 'buy' or 'sell', got {action!r}")
        price = leg.get("limit_price")
        ratio = leg.get("ratio_qty")
        if not _is_number(price) or not _is_number(ratio):
            raise ValueError(
                f"leg {leg.get('symbol')!r}: limit_price and ratio_qty must be numbers"
            )
        total += (1 if action == "buy" else -1) * price * ratio
    return total


def _check_net(proposal, thresholds):
    computed = _net_from_legs(proposal)
    reported = proposal.get("net_debit_credit")
    if not _is_number(reported):
        return False, f"reported_net={reported!r} is not a number", computed

    tolerance = thresholds["net_reconcile_tolerance"]
    delta = computed - reported
    detail = (
        f"computed_net={_money(computed)} vs reported_net={_money(reported)} "
        f"delta={_money(delta)} tolerance={tolerance} per_share=true qty_factor=none"
    )
    if abs(delta) > tolerance:
        qty = proposal.get("qty")
        hint = ""
        if _is_number(qty) and qty > 1 and abs(computed * qty - reported) <= tolerance:
            hint = (
                f" — reported net equals the per-share net times qty={qty}; the wire "
                f"limit is per unit of spread and qty is not a factor (C1)"
            )
        return False, detail + hint, computed
    return True, detail, computed


# ---------------------------------------------------------------------------
# Money caps — dollars, or a fraction of equity
# ---------------------------------------------------------------------------

def _resolve_cap(spec, account, label):
    """Resolve a configured cap into dollars.

    Returns ``(cap, basis_tokens, failed_closed_reason)``.

    * A number is dollars, and `basis_tokens` says so.
    * ``{"pct_of_equity": f}`` is resolved against the composed view's `equity`.
      A missing or non-numeric equity does NOT raise: the config is well-formed
      and the account read is not, which is a data-quality rejection, so it
      comes back as a reason to fail the check closed.
    * Anything else is a malformed config, which is a caller error and raises —
      laundering a bad config into a rejection would make it look like a
      considered decision.
    """
    if spec is None:
        return None, "", None
    if _is_number(spec):
        # No basis token: `cap=500.00` already says dollars, and adding a word
        # to every detail a dollar cap has ever produced would rewrite the
        # recorded reasoning of every decision made before this form existed.
        return float(spec), "", None
    if isinstance(spec, dict) and "pct_of_equity" in spec:
        pct = spec["pct_of_equity"]
        if not _is_number(pct) or pct <= 0:
            raise ValueError(
                f"{label}.pct_of_equity must be a positive number, got {pct!r}"
            )
        equity = account.get("equity")
        if not _is_number(equity):
            return None, f"cap_basis={pct:g}_of_equity equity=null", (
                f"{label} is configured as {pct:g} of equity and the composed "
                f"account view carries no numeric equity, so the cap cannot be "
                f"resolved — an unresolvable cap is not an absent one, and this "
                f"fails closed rather than passing unbounded"
            )
        return (round(pct * equity, 2),
                f"cap_basis={pct:g}_of_equity equity={_money(equity)}", None)
    raise ValueError(
        f"{label} must be a number of dollars or {{'pct_of_equity': <fraction>}}, "
        f"got {spec!r}"
    )


# ---------------------------------------------------------------------------
# max_loss_cap — the governor's own arithmetic
# ---------------------------------------------------------------------------

def _computed_max_loss(proposal, net):
    """Max loss in dollars, multiplier and qty applied. None where no cap applies.

    covered_call       None — the downside is the share position behind it,
                       bounded by coverage (2e), not by a standalone figure.
    cash_secured_put   (strike - credit) * 100 * qty
    vertical, debit    debit * 100 * qty
    vertical, credit   (width - credit) * 100 * qty
    """
    structure = proposal["structure"]
    qty = proposal["qty"]
    scale = _CONTRACT_MULTIPLIER * qty

    if structure == "covered_call":
        return None
    if structure == "cash_secured_put":
        strike = proposal["legs"][0]["strike"]
        # net is negative for a credit, so strike + net is strike - credit.
        return (strike + net) * scale

    strikes = [leg["strike"] for leg in proposal["legs"]]
    width = abs(strikes[0] - strikes[1])
    if net > 0:
        return net * scale
    return (width + net) * scale


def _check_max_loss_cap(proposal, max_loss, account, thresholds):
    structure = proposal["structure"]
    caps = thresholds["max_loss_cap"]
    if structure not in caps:
        raise ValueError(f"thresholds.max_loss_cap has no entry for {structure!r}")
    cap, basis, failed_closed = _resolve_cap(
        caps[structure], account, f"max_loss_cap.{structure}"
    )
    claimed = proposal.get("claimed_max_loss")

    if max_loss is None or (cap is None and failed_closed is None):
        return "max_loss_cap", True, (
            f"structure={structure} computed_max_loss={_money(max_loss)} cap=null — a "
            f"covered call's downside is the share position it is written against, "
            f"bounded by the coverage check (2e), not by a standalone max-loss cap"
        )

    detail = (
        f"structure={structure} computed_max_loss={_money(max_loss)} vs "
        f"cap={_money(cap)}{_basis(basis)} claimed_max_loss={_money(claimed)}"
    )
    if _is_number(claimed):
        divergence = max_loss - claimed
        detail += f" claim_divergence={_money(divergence)}"
        if abs(divergence) > 0.005:
            detail += (
                " — the claim is ADVISORY and did not enter this decision (2d); the "
                "divergence is recorded because a wrong claim is itself a finding"
            )

    if failed_closed is not None:
        return "max_loss_cap", False, detail + " — " + failed_closed
    if max_loss < 0:
        return "max_loss_cap", False, detail + (
            " — computed max loss is negative, which no defined-risk structure "
            "produces; failing closed rather than trusting the arithmetic"
        )
    return "max_loss_cap", max_loss <= cap, detail


# ---------------------------------------------------------------------------
# coverage — structure vs legs vs account state (2e)
# ---------------------------------------------------------------------------

def _check_coverage(proposal, account, max_loss, net):
    structure = proposal["structure"]
    qty = proposal["qty"]
    underlying = proposal["underlying"]
    position = account["positions"].get(underlying) or {}

    if structure == "covered_call":
        held = position.get("shares", 0)
        reserved = position.get("reserved_shares", 0)
        unreserved = held - reserved
        required = _CONTRACT_MULTIPLIER * qty
        detail = (
            f"structure=covered_call underlying={underlying} held_shares={held} "
            f"reserved_shares={reserved} unreserved_shares={unreserved} vs "
            f"required_shares={required} — shares already reserved against another "
            f"short call cannot cover this one"
        )
        return "coverage", unreserved >= required, detail

    if structure == "cash_secured_put":
        strike = proposal["legs"][0]["strike"]
        unreserved = account["cash"] - account["reserved_cash"]
        required = strike * _CONTRACT_MULTIPLIER * qty
        detail = (
            f"structure=cash_secured_put underlying={underlying} "
            f"cash={_money(account['cash'])} reserved_cash={_money(account['reserved_cash'])} "
            f"unreserved_cash={_money(unreserved)} vs required_cash={_money(required)}"
        )
        return "coverage", unreserved >= required, detail

    buying_power = account["buying_power"]
    detail = (
        f"structure=vertical_spread underlying={underlying} "
        f"buying_power={_money(buying_power)} vs "
        f"required_buying_power={_money(max_loss)} — measured against the governor's "
        f"computed max loss, never the claim"
    )
    return "coverage", buying_power >= max_loss, detail


# ---------------------------------------------------------------------------
# cash_floor — PROPOSED arithmetic, see tests/fixtures/governor/README.md
# ---------------------------------------------------------------------------

def _collateral(proposal, net):
    """Cash this trade ties up, beyond the premium that changes hands."""
    structure = proposal["structure"]
    scale = _CONTRACT_MULTIPLIER * proposal["qty"]
    if structure == "covered_call":
        return 0.0                                    # the shares are the collateral
    if structure == "cash_secured_put":
        return proposal["legs"][0]["strike"] * scale
    if net > 0:
        return 0.0                                    # a debit is already a cash outflow
    strikes = [leg["strike"] for leg in proposal["legs"]]
    return abs(strikes[0] - strikes[1]) * scale       # credit vertical: the wing width


def _check_cash_floor(proposal, account, net, thresholds):
    scale = _CONTRACT_MULTIPLIER * proposal["qty"]
    free_before = account["cash"] - account["reserved_cash"]
    premium_flow = -(net * scale)                     # credit positive, debit negative
    collateral = _collateral(proposal, net)
    cash_after = free_before + premium_flow - collateral
    floor = thresholds["cash_floor_pct"] * account["cash"]

    detail = (
        f"free_cash_before={_money(free_before)} premium_flow={_money(premium_flow)} "
        f"collateral={_money(collateral)} cash_after={_money(cash_after)} vs "
        f"floor={_money(floor)} floor_pct={thresholds['cash_floor_pct']}"
    )
    return "cash_floor", cash_after >= floor, detail


# ---------------------------------------------------------------------------
# churn_guard — re-entry window and minimum hold
# ---------------------------------------------------------------------------

def _check_churn(proposal, account, as_of, thresholds):
    underlying = proposal.get("underlying")
    ledger = account.get("ledger")
    if not isinstance(ledger, dict) or "recent_activity" not in ledger:
        return "churn_guard", False, (
            "not evaluated: account_state carries no ledger-derived recent_activity, "
            "so re-entry cannot be ruled out — failing closed"
        )

    activity = ledger["recent_activity"].get(underlying) or {}
    window = thresholds["churn_window_seconds"]
    min_hold = thresholds["min_hold_seconds"]

    since_open = _age(activity.get("last_open_at"), as_of)
    position_age = _age(activity.get("position_opened_at"), as_of)

    detail = (
        f"underlying={underlying} seconds_since_last_open={_seconds(since_open)} vs "
        f"churn_window_seconds={window} position_age_seconds={_seconds(position_age)} "
        f"vs min_hold_seconds={min_hold}"
    )

    if since_open is not None and since_open < window:
        return "churn_guard", False, detail + (
            " — re-entry on this underlying inside the churn window"
        )
    if position_age is not None and position_age < min_hold:
        return "churn_guard", False, detail + (
            " — the open position on this underlying is younger than the minimum hold"
        )
    return "churn_guard", True, detail


# ---------------------------------------------------------------------------
# market_open, and the x_ extensions
# ---------------------------------------------------------------------------

def _check_market_open(is_open):
    if is_open is None:
        return "market_open", False, (
            "is_open=unknown — no clock was supplied, only a bare as_of, so "
            "submission gating cannot be satisfied; failing closed (6c)"
        )
    return "market_open", bool(is_open), (
        f"is_open={str(bool(is_open)).lower()} — screening and proposing run at any "
        f"time; order submission is gated on the market being open (6c)"
    )


def _check_position_cap(proposal, account, thresholds):
    """Not seam vocabulary, so it rides the agreed x_ prefix (3a)."""
    underlying = proposal.get("underlying")
    ledger = account.get("ledger")
    if not isinstance(ledger, dict) or "open_positions" not in ledger:
        return "x_position_cap", False, (
            "not evaluated: account_state carries no ledger-derived open_positions; "
            "failing closed"
        )

    caps = thresholds["position_caps"]
    open_positions = ledger["open_positions"]
    for_underlying = open_positions.get(underlying, 0)
    total = sum(open_positions.values())
    per_cap = caps["max_open_per_underlying"]
    total_cap = caps["max_open_positions"]

    detail = (
        f"underlying={underlying} open_for_underlying={for_underlying} vs "
        f"max_open_per_underlying={per_cap} open_total={total} vs "
        f"max_open_positions={total_cap}"
    )
    passed = for_underlying < per_cap and total < total_cap
    return "x_position_cap", passed, detail


def _check_max_expiry(proposal, thresholds):
    """The scored-run expiry bound. Not seam vocabulary, so it rides `x_` (3a).

    **Why this is not `structure_valid`.** The pinned core vocabulary is closed
    to the governor lead: `structure_valid` is defined in 3a as "the declared
    structure matches the actual leg composition, and leg `ratio_qty` values are
    positive integers with GCD 1". An expiry bound is neither, and quietly
    widening a pinned check to hold an unrelated rule would be a seam change
    made by not writing one down. `x_` is the extension point the seam grants
    for exactly this, and the dashboard renders `x_` checks generically.

    **Why the bound exists at all.** Scoring reads TOTAL ACCOUNT EQUITY at EOD
    Thursday Sep 3 (`EVENT_FACTS.md`, Alpaca FAQ, `[primary]`). A short premium
    position still open after that is scored at its *mark* — unrealised and
    moving — rather than at the premium collected. Positions that resolve on or
    before the bound convert premium into scored equity instead of leaving
    mark-to-market residue in the number the judges read.

    This is a **scored-run bound, not a trading judgement**, which is why it is
    DECIDED rather than PROPOSED and why it lives in config with its reasoning
    attached. `null` means no bound is configured; that is the honest value for
    a run that is not the scored one, and it is stated in the detail rather than
    left as a silent pass.
    """
    bound = thresholds["max_expiry_date"]
    legs = proposal.get("legs") or []
    expiries = [leg.get("expiry") for leg in legs]
    shown = ",".join(str(e) for e in expiries) or "none"

    if bound is None:
        return "x_max_expiry", True, (
            f"max_expiry_date=null legs_expire={shown} — no scored-run expiry bound "
            f"is configured for this run"
        )

    # Every leg, not the first: a structure is only as short-dated as its
    # longest leg, and a spread with one leg past the bound leaves exactly the
    # open mark-to-market position the bound exists to prevent.
    late = [e for e in expiries if not isinstance(e, str) or e > bound]
    detail = (
        f"max_expiry_date={bound} legs_expire={shown} legs={len(legs)} "
        f"late_legs={len(late)}"
    )
    if late:
        return "x_max_expiry", False, detail + (
            " — scoring reads total account equity at the bound, so a leg living "
            "past it is scored at its mark rather than as collected premium"
        )
    return "x_max_expiry", True, detail


def _check_total_open_risk(proposal, account, max_loss, thresholds):
    """Portfolio-level risk cap. PROPOSED, and rides `x_` (3a).

    Per-structure caps bound one trade. Four trades each inside their own cap
    can still put the whole account at risk, and on a scored account the number
    the judges read is the account's, not the trade's. So this sums the
    governor's OWN computed max loss across every position the ledger says is
    bearing risk, adds this proposal's, and compares the total against the cap.

    The open figure is composed from the ledger and handed in — this module does
    no I/O (property 3) — but it must be composed with :func:`computed_max_loss`,
    not with anything a position claimed about itself.

    A covered call contributes nothing here and says so: it has no standalone
    max-loss figure (2e), and inventing one for an aggregate would be exactly
    the kind of made-up number this component exists to refuse. Those positions
    are counted separately as `unpriced_positions` so the reader can see that
    the total is a total over what is *priceable*, not over everything.
    """
    spec = thresholds.get("x_total_open_risk")
    if spec is None:
        return "x_total_open_risk", True, (
            "x_total_open_risk=null — no portfolio-level open-risk cap is "
            "configured for this run"
        )

    cap, basis, failed_closed = _resolve_cap(spec, account, "x_total_open_risk")

    ledger = account.get("ledger")
    open_risk = ledger.get("open_risk") if isinstance(ledger, dict) else None
    if not isinstance(open_risk, dict) or not _is_number(open_risk.get("total")):
        return "x_total_open_risk", False, (
            f"not evaluated: account_state carries no ledger-derived open_risk "
            f"total, so the risk already on the book is unknown — failing closed "
            f"rather than treating an unknown book as an empty one. "
            f"cap={_money(cap)}{_basis(basis)}"
        )

    already = float(open_risk["total"])
    unpriced = open_risk.get("unpriced_positions", 0)
    counted = open_risk.get("counted_positions", 0)
    proposed = max_loss if _is_number(max_loss) else 0.0
    total = already + proposed

    detail = (
        f"open_risk_before={_money(already)} counted_positions={counted} "
        f"unpriced_positions={unpriced} proposed_max_loss={_money(proposed)} "
        f"total_open_risk={_money(total)} vs cap={_money(cap)}{_basis(basis)}"
    )
    if max_loss is None:
        detail += (
            " — the proposal is a covered call and contributes 0: it carries no "
            "standalone max-loss figure (2e) and is bounded by coverage instead"
        )
    if failed_closed is not None:
        return "x_total_open_risk", False, detail + " — " + failed_closed
    return "x_total_open_risk", total <= cap, detail


# ---------------------------------------------------------------------------
# Small shared pieces
# ---------------------------------------------------------------------------

def _basis(basis):
    """The cap's basis, as a leading-space suffix, or nothing at all.

    A dollar cap adds no token: `cap=500.00` already says what it is, and a
    percentage cap is the only one whose resolved figure needs its derivation
    written beside it.
    """
    return f" {basis}" if basis else ""


def _check(rule, passed, detail):
    return {"rule": rule, "passed": bool(passed), "detail": detail}


def _reason(approved, checks):
    if approved:
        return (
            f"approved: all {len(checks)} checks passed, max loss computed "
            f"independently of the proposal's claim"
        )
    failed = [check["rule"] for check in checks if not check["passed"]]
    first = next(check for check in checks if not check["passed"])
    return f"rejected on {', '.join(failed)} — {first['detail']}"


def _is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _money(value):
    return "null" if not _is_number(value) else f"{value:.2f}"


def _seconds(value):
    return "null" if value is None else f"{value:.0f}"


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age(timestamp, as_of):
    """Seconds between `timestamp` and `as_of`, or None if there is no timestamp."""
    parsed = _parse_ts(timestamp)
    if parsed is None:
        return None
    return (as_of - parsed).total_seconds()
