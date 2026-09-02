#!/usr/bin/env python3
"""End-to-end run: live chain -> screener -> governor -> ledger [-> a real order].

The point of this script is that it is the whole pipeline, running for real, on
real data, against a real paper account. Without it, GlassBox is five green
contract suites and a claim.

**WHICH ACCOUNT.** Two paper accounts exist and nothing in the code
distinguishes them: the shared DEV account both pods experiment on, and the
SCORED competition account whose total equity at EOD 2026-09-03 is the judged
number. `--env` selects which, and **it defaults to `.env` (dev)**, so reaching
the scored account is always something a human typed. `config/profiles.json`
maps the env file to its account number, its ledger, its demo sample and its
governor config; the ledgers are separate files and a scored order can never
land in the dev ledger or be judged under the dev config.

**The identity guard runs before anything else.** The broker is asked who it is
over the same connection that would carry an order, and the run aborts if the
answer is not the account this profile names — before the chain is fetched, let
alone screened. The executor asks again immediately before submitting.

**By default it stops one step short of the broker.** Every request the data
path makes goes through a session that raises on any URL containing `/orders`
and has no POST method at all, so a dry run cannot submit even by accident. That
guard is printed at the top of the run rather than asserted in a comment.

**With `--submit` it goes the last step**, and submits the approved proposal as
a REAL order through `glassbox.executor` and Alpaca's official SDK. That flag
exists so the decision is a human typing it, never a default. When it is set the
run switches to **autopilot** mode: a submitted order recorded as `approve` with
`approved_by` null would be a ledger entry claiming a human confirmed something
nobody confirmed.

What it does, in order:

  0. Read `/v2/account` through the executor's own transport and REFUSE unless
     the account number is the one this profile names.
  1. Resolve `as_of` from the LIVE `/v2/clock` and `/v2/calendar` (seam 6c),
     taken when the read COMPLETED, not when it started.
  2. Fetch the SPY chain inside the configured DTE band — clamped to the scored
     run's `max_expiry_date` — and its snapshots.
  3. Screen it (shape 6). Fail-closed rejections are counted by reason.
  4. Build TWO proposals from the ACCEPTED set with a small helper:
       (a) a defined-risk vertical priced off real bids and asks, narrowed to
           the config's liquidity window, which should PASS every check;
       (b) a deliberately bad cash-secured put — over-sized, with a
           `claimed_max_loss` a fraction of the real figure — which MUST be
           rejected, on the arithmetic rather than on the claim.
     With `--qty auto`, (a) is sized by ASKING THE GOVERNOR: propose, read the
     `max_loss_cap` detail, and step down until it approves.
  5. Fetch RAW account state (2b RAW) and compose the governor's view against
     the profile's ledger (A2 b: reservations are ledger-derived).
  6. Govern both. The run STOPS, having written nothing, if the bad one is
     approved or the good one fails on anything but `market_open`.
  7. Append both root entries to the profile's ledger (gitignored) and a
     scrubbed copy to its demo sample (committed).
  8. Print both verdicts with full `checks[]` detail, the folded chains, and a
     REPLAY of each root proving the recorded verdict follows from the recorded
     inputs.
  9. With `--submit`: hand the approved root to the executor, follow the order
     to a terminal state, and append `submitted` / `filled` / `partial_fill` /
     `broker_rejected` follow-ups chained on its `root_id` (5a).

Usage:
    python scripts/dry_run.py                                  # DEV, no order
    python scripts/dry_run.py --submit                         # DEV, one order
    python scripts/dry_run.py --env .env.competition --submit --qty 1
    python scripts/dry_run.py --env .env.competition --submit --qty auto
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from glassbox import governor as governor_mod  # noqa: E402
from glassbox import ledger as ledger_mod  # noqa: E402
from glassbox.datafeed import (  # noqa: E402
    DataFeed,
    load_config,
    load_dotenv,
    parse_wire_ts,
    resolve_as_of,
)
from glassbox.executor import (  # noqa: E402
    BROKER_STATUS_MAP,
    AlpacaPyTransport,
    Executor,
    assert_account_identity,
)
from glassbox.governor import govern  # noqa: E402
from glassbox.ledger import iso_utc  # noqa: E402
from glassbox.screener import screen_chain  # noqa: E402

# Config lives in files, never in this script (CLAUDE.md). Two of these still
# sit under tests/ because that is where they were born with their golden
# fixtures; moving them to config/ is a MOVE, never a copy — a second copy of a
# tunable is the failure mode the rule exists to prevent.
DATAFEED_CONFIG = REPO / "config" / "datafeed.PROPOSED.json"
SCREENER_THRESHOLDS = REPO / "tests" / "fixtures" / "thresholds.PROPOSED.json"

#: Which env file means which account, ledger and governor config. The one place
#: that knows, so a run cannot silently write scored orders into the dev ledger.
PROFILES = REPO / "config" / "profiles.json"

#: Re-exported for readers of this script. The set — and the composition of the
#: whole account view — belongs to the GOVERNOR (A2 b) and was promoted there on
#: 2026-09-02, which is the commit that also stopped `churn_guard` being blind to
#: a filled position. Nothing about it is decided here any more.
RISK_BEARING = governor_mod.RISK_BEARING

#: A bound on the sizing search, so a mis-stated cap cannot walk the governor up
#: to an absurd quantity. It is not a risk limit — the governor's caps are — it
#: is a limit on how many times this script is willing to ask.
_MAX_QTY_SEARCH = 50

RULE = "=" * 78
THIN = "-" * 78


class NoOrdersSession:
    """A requests.Session that physically cannot reach an orders endpoint.

    The dry run's central claim is "no order submission of any kind". A comment
    saying so is worth nothing; this raises. It also counts requests, so the run
    can report exactly how much it touched the venue.
    """

    def __init__(self):
        import requests

        self._inner = requests.Session()
        self.count = 0

    def get(self, url, **kwargs):
        if "/orders" in url:
            raise AssertionError(
                f"the data path tried to reach an orders endpoint: {url}. Nothing "
                f"in the data path may submit; the executor is the only component "
                f"that may, and it holds its own transport"
            )
        self.count += 1
        return self._inner.get(url, **kwargs)

    def post(self, *args, **kwargs):
        raise AssertionError(
            "the data path does not write to the broker. There is no POST path in "
            "it, by construction"
        )

    put = patch = delete = post


def stamped(body, as_of):
    """Re-stamp a completed read with the moment it FINISHED.

    A read is true as of when it **finished**, not when it started. The venue
    served the last page tens of seconds after the first, so a run that stamps
    `as_of` up front is claiming a timestamp that precedes quotes it is holding —
    and the screener rejects a quote dated after its own `as_of` as `stale_quote`,
    correctly, because it cannot be reconciled with a read that claims to come
    first. Off-hours this changes nothing (`as_of` is the last close, already
    behind every quote); inside a session it is the difference between screening
    a chain and rejecting all of it.

    The data layer stamps whatever the caller hands it. **Choosing the right
    moment is the caller's job** (6c), which is why this lives here.
    """
    return {**body, "as_of": iso_utc(as_of)}


# ---------------------------------------------------------------------------
# Profiles — which account this run is for
# ---------------------------------------------------------------------------

def load_profile(env_file):
    """Resolve the env file the caller named into a whole run profile.

    An env file with no profile is a hard stop rather than a default: guessing
    which account an unknown key pair belongs to is precisely the guess this
    file exists to remove.
    """
    doc = json.loads(PROFILES.read_text(encoding="utf-8"))
    profiles = doc["profiles"]
    if env_file not in profiles:
        raise SystemExit(
            f"no run profile for env file {env_file!r}. "
            f"{PROFILES.relative_to(REPO)} knows: {', '.join(sorted(profiles))}. "
            f"Add a profile naming its account number, ledger, demo sample and "
            f"governor config — this script will not guess which account a key "
            f"pair belongs to"
        )
    profile = dict(profiles[env_file])
    profile["env_file"] = env_file
    for key in ("name", "account_number", "ledger", "demo_sample",
                "governor_thresholds", "scored"):
        if key not in profile:
            raise SystemExit(f"profile {env_file!r} is missing {key!r}")
    for key in ("ledger", "demo_sample", "governor_thresholds"):
        profile[key] = REPO / profile[key]
    return profile


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def content_hash(path):
    """shape 3: config_version is a CONTENT hash, so it cannot drift silently."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_version():
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def entry_id(ts, proposal, config_version):
    """Unique per decision, and content-tagged so two ids never mean one entry."""
    digest = hashlib.sha256(
        json.dumps(proposal, sort_keys=True).encode() + config_version.encode()
    ).hexdigest()[:10]
    return f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{digest}"


# ---------------------------------------------------------------------------
# The account: identity first, then equity
# ---------------------------------------------------------------------------

def confirm_account(transport, profile, config):
    """Ask the broker who it is, and refuse unless it is who we were told.

    Returns ``(identity, equity, body)``. The equity comes from the SAME read as
    the identity, so the number a percentage cap resolves against and the
    account it was read from cannot be two different accounts.

    `/v2/account` carries `equity`; the data layer's 2b RAW shape deliberately
    does not, and widening a signed seam shape to carry a number one caller
    wants is a seam change made by not writing one down. So the executor's own
    transport supplies it, which is also the transport whose identity has just
    been confirmed.
    """
    body = transport.get_account()
    identity = assert_account_identity(
        body,
        expected_account_number=profile["account_number"],
        trading_base_url=config["trading_base_url"],
    )
    try:
        equity = float(body.get("equity"))
    except (TypeError, ValueError):
        raise SystemExit(
            "/v2/account returned no numeric equity. Every cap on this run is a "
            "fraction of equity, and a cap that cannot be resolved is not a cap; "
            "stopping rather than running uncapped"
        ) from None
    return identity, equity, body


# ---------------------------------------------------------------------------
# The governor's composed account view (A2 b) — PROMOTED to the governor
# ---------------------------------------------------------------------------
#
# `compose_account_view` used to live here, and that is exactly how a filled
# position became invisible to `churn_guard`: this script composed
# `recent_activity` over the chains that were still IN FLIGHT, and a filled
# chain is terminal as an ORDER. A2(b) always assigned the composition to the
# governor; on 2026-09-02 it was moved there, with GB-C criteria of its own, and
# this script imports it. Nothing about what the governor sees is decided in a
# harness any more.

compose_account_view = governor_mod.compose_account_view


# ---------------------------------------------------------------------------
# The proposal helper — small, and deliberately not a strategist
# ---------------------------------------------------------------------------

def quote_of(snapshots, symbol):
    return (snapshots.get(symbol) or {}).get("latestQuote") or {}


def leg(symbol, action, option_type, strike, expiry, limit_price):
    return {
        "symbol": symbol, "action": action, "option_type": option_type,
        "strike": float(strike), "expiry": expiry, "ratio_qty": 1,
        "limit_price": round(float(limit_price), 2),
    }


def net_of(legs):
    """C1: per share, for ONE unit of the spread. qty is NOT a factor."""
    return round(sum((1 if l["action"] == "buy" else -1) * l["limit_price"] * l["ratio_qty"]
                     for l in legs), 2)


def estimate_spot(accepted, snapshots):
    """Put-call parity across the accepted set, for STRIKE SELECTION ONLY.

    No decision depends on this number: the governor never sees it, and it is
    printed with its own spread so a reader can judge it. It exists so the
    proposals below sit where a human would actually put them rather than at an
    arbitrary strike.
    """
    calls = {(c["expiry"], c["strike"]): c for c in accepted if c["option_type"] == "call"}
    puts = {(c["expiry"], c["strike"]): c for c in accepted if c["option_type"] == "put"}
    estimates = []
    for key in set(calls) & set(puts):
        call_q, put_q = quote_of(snapshots, calls[key]["symbol"]), quote_of(snapshots, puts[key]["symbol"])
        call_mid = (call_q["bp"] + call_q["ap"]) / 2
        put_mid = (put_q["bp"] + put_q["ap"]) / 2
        estimates.append(key[1] + call_mid - put_mid)
    if not estimates:
        return None, 0, (None, None)
    estimates.sort()
    return (estimates[len(estimates) // 2], len(estimates),
            (estimates[0], estimates[-1]))


def liquidity_reasons(symbol, window, contracts_by_symbol, snapshots, *, short_leg):
    """Why this contract is outside the config's liquidity window, if it is.

    Applied AFTER the screener, which has already failed closed on null greeks,
    a missing bid or ask, a stale quote and a missing snapshot (shape 6). This is
    the second, narrower pass: a contract can be perfectly well quoted and still
    be a bad thing to sell into a one-day book.

    The two-sided quote and open-interest tests apply to BOTH legs — you have to
    be able to trade the wing too — and the delta band applies to the SHORT leg
    only, because it is the leg that expresses where the position sits relative
    to spot. Every test FAILS CLOSED on a value it cannot read: an unknown open
    interest is not a large one.
    """
    if window is None:
        return []
    reasons = []
    contract = contracts_by_symbol.get(symbol) or {}

    raw_oi = contract.get("open_interest")
    try:
        open_interest = int(float(raw_oi))
    except (TypeError, ValueError):
        open_interest = None
    if open_interest is None or open_interest < window["min_open_interest"]:
        reasons.append("open_interest")

    if window["require_two_sided_quote"]:
        quote = quote_of(snapshots, symbol)
        bid, ask = quote.get("bp"), quote.get("ap")
        two_sided = (
            isinstance(bid, (int, float)) and not isinstance(bid, bool) and bid > 0
            and isinstance(ask, (int, float)) and not isinstance(ask, bool) and ask > 0
            and ask >= bid
        )
        if not two_sided:
            reasons.append("one_sided_quote")

    if short_leg:
        greeks = (snapshots.get(symbol) or {}).get("greeks") or {}
        delta = greeks.get("delta")
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            reasons.append("null_delta")
        elif not (window["short_leg_abs_delta_min"] <= abs(delta)
                  <= window["short_leg_abs_delta_max"]):
            reasons.append("delta_band")

    return reasons


def build_pass_vertical(accepted, snapshots, contracts_by_symbol, spot, width,
                        window, qty=1, report=None):
    """A defined-risk put vertical, priced off real bids and asks.

    Sold at the BID and bought at the ASK — the side of the spread a taker
    actually gets. Pricing a proposal at the mid makes it look better than it is,
    which is the sort of small dishonesty this whole project exists to refuse.

    Chosen: the widest-premium `width`-wide pair below spot whose legs are both
    in the ACCEPTED set AND inside the config's liquidity window. The governor
    recomputes everything about it from scratch and never sees the window.
    """
    puts = sorted(
        (c for c in accepted
         if c["option_type"] == "put" and (spot is None or c["strike"] < spot)),
        key=lambda c: (c["expiry"], c["strike"]),
    )
    by_key = {(c["expiry"], c["strike"]): c for c in puts}
    counts = {} if report is None else report

    best = None
    for short in puts:
        short_out = liquidity_reasons(short["symbol"], window, contracts_by_symbol,
                                      snapshots, short_leg=True)
        if short_out:
            for reason in short_out:
                counts[f"short_{reason}"] = counts.get(f"short_{reason}", 0) + 1
            continue
        long_leg = by_key.get((short["expiry"], short["strike"] - width))
        if long_leg is None:
            counts["no_wing_at_width"] = counts.get("no_wing_at_width", 0) + 1
            continue
        long_out = liquidity_reasons(long_leg["symbol"], window, contracts_by_symbol,
                                     snapshots, short_leg=False)
        if long_out:
            for reason in long_out:
                counts[f"long_{reason}"] = counts.get(f"long_{reason}", 0) + 1
            continue

        short_q, long_q = quote_of(snapshots, short["symbol"]), quote_of(snapshots, long_leg["symbol"])
        legs = [
            leg(short["symbol"], "sell", "put", short["strike"], short["expiry"], short_q["bp"]),
            leg(long_leg["symbol"], "buy", "put", long_leg["strike"], long_leg["expiry"], long_q["ap"]),
        ]
        net = net_of(legs)
        # A "credit" at or beyond the width of the wings is a quoted arbitrage,
        # not a trade: it implies the short leg's bid exceeds the long leg's ask
        # by more than the strikes are apart. Off-hours indicative quotes throw
        # these off regularly. The governor would fail closed on the resulting
        # negative max loss, correctly — but proposing it in the first place is
        # not what "plausible" means, so it is filtered here rather than leaned on.
        if -net >= width:
            counts["quoted_arbitrage"] = counts.get("quoted_arbitrage", 0) + 1
            continue
        counts["candidates"] = counts.get("candidates", 0) + 1
        if best is None or net < best[0]:
            best = (net, legs, short, long_leg)
    if best is None:
        return None
    net, legs, short, long_leg = best

    # The governor computes max loss itself; these are the strategist's stated
    # belief and are ADVISORY (2d). They are stated HONESTLY here so that the
    # only dishonest proposal in this run is the one that is meant to be — and
    # they scale with qty, because a claim that silently described one lot of a
    # five-lot order would be a small lie of exactly the kind this refuses.
    credit = -net if net < 0 else 0.0
    per_unit_loss = (width - credit) if net < 0 else net
    per_unit_gain = credit if net < 0 else (width - net)
    return {
        "underlying": "SPY",
        "structure": "vertical_spread",
        "qty": qty,
        "legs": legs,
        "net_debit_credit": net,
        "rationale": (
            f"Defined-risk {width:.0f}-wide SPY put vertical expiring "
            f"{short['expiry']}: short the {short['strike']:.0f}, long the "
            f"{long_leg['strike']:.0f}, {qty} lot(s). Risk is capped at the width "
            f"of the wings whatever SPY does. Both legs cleared the config's "
            f"liquidity window (two-sided quote, open interest, and the short "
            f"leg inside the delta band). Priced at the bid on the short leg and "
            f"the ask on the long leg — the side a taker actually gets. "
            f"Hand-authored by the harness; no strategist and no LLM was involved."
        ),
        "claimed_max_loss": round(per_unit_loss * 100 * qty, 2),
        "claimed_max_gain": round(per_unit_gain * 100 * qty, 2),
    }


def build_reject_csp(accepted, snapshots, spot, qty=2):
    """A DELIBERATELY BAD cash-secured put. It must be rejected.

    Three defects, on purpose, and each is a different kind of wrong:

      * **Over-sized.** `qty` puts at this strike need more collateral than the
        account has, and leave it below the cash floor even if it had it.
      * **A false claim.** `claimed_max_loss` is 250 against a real figure two
        orders of magnitude larger. The governor must reject on ITS OWN
        arithmetic and record the divergence, not reject because the claim
        looked small.
      * **Nothing else.** The structure is valid and the net reconciles exactly,
        so the risk band actually runs. A proposal that failed the gates would
        never reach the checks this case exists to exercise.

    Deliberately NOT narrowed by the liquidity window: this proposal exists to
    be refused by the governor, and pre-filtering it would be testing the filter.
    """
    puts = [c for c in accepted
            if c["option_type"] == "put" and (spot is None or c["strike"] < spot)]
    if not puts:
        return None
    short = max(puts, key=lambda c: (c["strike"], c["expiry"]))
    bid = quote_of(snapshots, short["symbol"])["bp"]
    legs = [leg(short["symbol"], "sell", "put", short["strike"], short["expiry"], bid)]
    return {
        "underlying": "SPY",
        "structure": "cash_secured_put",
        "qty": qty,
        "legs": legs,
        "net_debit_credit": net_of(legs),
        "rationale": (
            f"Sell {qty} SPY {short['strike']:.0f} puts expiring {short['expiry']} "
            f"for the premium. DELIBERATELY BAD: this is the adversarial half of "
            f"the run. The position is larger than the account can secure and "
            f"the stated max loss is a fiction."
        ),
        "claimed_max_loss": 250.00,
        "claimed_max_gain": round(-net_of(legs) * 100 * qty, 2),
    }


# ---------------------------------------------------------------------------
# Sizing — by asking the governor, never by computing the cap here
# ---------------------------------------------------------------------------

def detail_fields(detail):
    """The seam's `k=v` detail convention, parsed. Shape 3's own example is
    `computed_max_loss=250.00 vs cap=500.00`."""
    fields = {}
    for token in (detail or "").split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


def detail_for(verdict, rule):
    for check in verdict["checks"]:
        if check["rule"] == rule:
            return check["detail"]
    return ""


def failing_rules(verdict):
    return [c["rule"] for c in verdict["checks"] if not c["passed"]]


def size_by_asking_the_governor(build, run_governor, ceiling=_MAX_QTY_SEARCH):
    """The largest qty the governor will approve, found by asking it.

    **This function does not know what the cap is.** It builds one lot, reads
    the `max_loss_cap` check's own detail for the figures the governor used, and
    from those takes a FIRST GUESS at how many lots fit. Then it proposes that
    size and steps down until the governor says yes. Every size is a real
    verdict from the real governor on a real proposal; the arithmetic here only
    decides which question to ask first, and if it guesses badly the descent
    corrects it.

    Computing the answer instead — reading the config, applying the percentage,
    dividing — would mean two implementations of the cap, and the day they
    disagree is the day an order is placed under a limit nothing enforced.

    Returns ``(proposal, verdict, attempts)``; the proposal is the one lot that
    was refused when nothing was approvable, so the caller always has checks to
    show.
    """
    attempts = []

    one = build(1)
    verdict = run_governor(one)
    attempts.append((1, verdict))
    if verdict["approved"]:
        seed = _seed_from_max_loss_detail(verdict, ceiling)
    else:
        # A refusal at one lot is not a sizing problem, and stepping down from
        # one lot is not a thing. Hand it back with its checks.
        return one, verdict, attempts

    if seed <= 1:
        return one, verdict, attempts

    best = (one, verdict)
    for qty in range(seed, 1, -1):
        proposal = build(qty)
        result = run_governor(proposal)
        attempts.append((qty, result))
        if result["approved"]:
            best = (proposal, result)
            break
    return best[0], best[1], attempts


def _seed_from_max_loss_detail(verdict, ceiling):
    """How many lots the governor's OWN recorded figures suggest might fit.

    A guess, and treated as one: it is only the first size proposed, and every
    size after it is another real verdict.
    """
    fields = detail_fields(detail_for(verdict, "max_loss_cap"))
    try:
        one_lot = float(fields["computed_max_loss"])
        cap = float(fields["cap"])
    except (KeyError, TypeError, ValueError):
        return 1
    if one_lot <= 0:
        return 1
    return max(1, min(ceiling, int(cap // one_lot)))


# ---------------------------------------------------------------------------
# Ledger, and the demo mirror
# ---------------------------------------------------------------------------

#: Dropped from a demo copy. A shape 5 entry carries balances and share counts,
#: not account identity, so on the dev profile this removes nothing and the run
#: REPORTS how many fields it dropped — "scrubbed" as a measured fact rather
#: than a promise.
_DEMO_SCRUB = ("account_number", "account_id", "email", "owner", "api_key")


class DemoMirror:
    """The committed, scrubbed copy of a ledger.

    `keep` is the exception list, and on the scored profile it holds
    `account_number`: the competition account id is a REQUIRED DISCLOSURE for
    the submission, so a sample that scrubbed it would be a sample that could
    not prove which account traded. It is an identifier, not a credential, and
    the credential scan below runs over the bytes either way.
    """

    def __init__(self, path, secrets, keep=()):
        self.path = path
        self.secrets = secrets
        self.drop = tuple(f for f in _DEMO_SCRUB if f not in keep)
        self.kept = tuple(f for f in _DEMO_SCRUB if f in keep)
        self.dropped_total = 0

    def scrub(self, entry):
        dropped = []

        def walk(value, path=""):
            if isinstance(value, dict):
                out = {}
                for key, item in value.items():
                    if key in self.drop:
                        dropped.append(f"{path}.{key}".lstrip("."))
                        continue
                    out[key] = walk(item, f"{path}.{key}")
                return out
            if isinstance(value, list):
                return [walk(item, f"{path}[]") for item in value]
            return value

        scrubbed = walk(entry)
        text = json.dumps(scrubbed)
        for secret in self.secrets:
            if secret and len(secret) >= 12 and secret in text:
                raise SystemExit("ABORT: a credential reached a ledger entry. Stop.")
        self.dropped_total += len(dropped)
        return scrubbed, dropped

    def append(self, entry):
        scrubbed, dropped = self.scrub(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(ledger_mod.serialize(scrubbed) + "\n")
        return dropped


def write_root(dev, mirror, *, ts, as_of, proposal, verdict, snapshot,
               config_version, code_sha):
    ident = entry_id(ts, proposal, config_version)
    status = "approved_pending" if verdict["approved"] else "governor_rejected"
    entry = dev.append_root(
        id=ident, ts=ts, as_of=as_of, mode=verdict["mode"], status=status,
        config_version=config_version,
        prompt_version=None,      # hand-authored: no LLM produced this proposal
        code_version=code_sha,
        approved_by=None, approved_at=None,   # nobody has confirmed yet (5a)
        snapshot=snapshot, proposal=proposal, verdict=verdict,
    )
    mirror.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def show_verdict(label, proposal, verdict):
    print(f"\n{RULE}\n{label}\n{RULE}")
    print(f"  structure       : {proposal['structure']}  qty={proposal['qty']}")
    for l in proposal["legs"]:
        print(f"  leg             : {l['action']:<4} {l['symbol']}  "
              f"strike={l['strike']:<8.2f} expiry={l['expiry']}  "
              f"limit={l['limit_price']:.2f}")
    print(f"  net_debit_credit: {proposal['net_debit_credit']:+.2f} per share, "
          f"one unit ({'CREDIT' if proposal['net_debit_credit'] < 0 else 'DEBIT'})")
    print(f"  claimed_max_loss: {proposal['claimed_max_loss']:.2f}  (ADVISORY — "
          f"the governor never reads it as an input)")
    print(f"\n  VERDICT         : "
          f"{'APPROVED' if verdict['approved'] else 'REJECTED'}   "
          f"mode={verdict['mode']}  config={verdict['config_version'][:19]}...")
    print(f"  reason          : {verdict['reason']}")
    print(f"\n  checks[] ({len(verdict['checks'])}):")
    for check in verdict["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"    [{mark}] {check['rule']}")
        for line in _wrap(check["detail"], 68):
            print(f"           {line}")


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# The real thing
# ---------------------------------------------------------------------------

#: How long to follow an order before giving up on a terminal state. A limit
#: order may simply not fill, which is a fact about the market and not a
#: failure; the chain is left in flight and says so.
_FOLLOW_SECONDS = 90
_POLL_SECONDS = 3


def submit_for_real(dev, mirror, root, config, profile, transport,
                    governor_thresholds):
    """Submit the approved root as a REAL order, and follow it to a terminal state.

    This is the only function in the repo that causes a position to exist. It
    runs solely because a human typed --submit.

    Everything it needs was decided before it was called: the proposal was
    screened from live data, the governor approved it on its own arithmetic, and
    the root entry is already on disk with the id that the order's
    `client_order_id` embeds. This function adds no judgement of its own — it
    hands the entry to the executor and writes down what the broker says.
    """
    print(f"\n{RULE}\n9. SUBMIT — a REAL order on the {profile['name'].upper()} "
          f"paper account\n{RULE}")

    executor = Executor(ledger=dev, transport=transport, config=config,
                        env=os.environ,
                        expected_account_number=profile["account_number"])

    payload = executor.build_order_request(root)
    print(f"  client_order_id : {payload['client_order_id']}")
    print(f"                    = ORDER_ID_PREFIX + the ROOT entry id, so a retry")
    print(f"                      is refused by the broker rather than opening a")
    print(f"                      second position (shape 4)")
    print(f"  order_class     : {payload.get('order_class', 'simple (single-leg, 4a)')}")
    print(f"  qty             : {payload['qty']}   type={payload['type']} "
          f"tif={payload['time_in_force']}")
    print(f"  limit_price     : {payload['limit_price']}"
          + ("  (SIGNED net, mleg)" if payload.get("order_class") == "mleg"
             else "  (abs(net), positive — 4a)"))
    for wire in payload.get("legs") or [payload]:
        print(f"  leg             : {wire['side']:<4} {wire['symbol']}  "
              f"position_intent={wire['position_intent']}")

    result = executor.submit(root, ts=datetime.now(timezone.utc))
    mirror.append(result["entry"])
    order = result["order"]
    print(f"\n  identity re-confirmed at submission: "
          f"{executor.identity['account_number']}")
    print(f"  SUBMITTED.")
    print(f"    broker order_id : {order['order_id']}")
    print(f"    broker status   : {order['status']}")
    print(f"    resolved_existing: {result['resolved_existing']} "
          f"(True would mean this was a retry the broker refused as a duplicate)")
    print(f"    ledger follow-up: {result['entry']['id']}  status=submitted "
          f"root_id={result['entry']['root_id']}")

    # -- follow it ---------------------------------------------------------
    print(f"\n  Following the order for up to {_FOLLOW_SECONDS}s "
          f"(a limit order not filling is a fact about the market, not a failure):")
    last = "submitted"
    deadline = time.monotonic() + _FOLLOW_SECONDS
    while time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)
        broker = transport.get_order_by_client_id(payload["client_order_id"])
        if broker is None:
            print("    broker returned no order for that client_order_id — stopping")
            break
        status = BROKER_STATUS_MAP.get(broker.get("status"))
        if status is None:
            print(f"    unmapped broker status {broker.get('status')!r} — stopping "
                  f"rather than guessing (the shape 5 vocabulary is closed)")
            break
        if status != last:
            entry = executor.record_transition(
                root["id"], broker, ts=datetime.now(timezone.utc)
            )
            mirror.append(entry)
            print(f"    {broker.get('status'):<18} -> ledger {status:<14} "
                  f"entry={entry['id']}")
            last = status
        if ledger_mod.is_terminal(status):
            break
    else:
        print(f"    still in flight after {_FOLLOW_SECONDS}s")

    # -- the chain, and the replay ----------------------------------------
    entries = dev.read_entries()
    chain = ledger_mod.fold_chain(entries, root["id"])
    status, terminal = ledger_mod.current_status(entries, root["id"])
    print(f"\n{THIN}\n10. THE CHAIN, folded by root_id\n{THIN}")
    print(f"  root {root['id']}   status={status} terminal={terminal} "
          f"entries={len(chain['entries'])}")
    for link in chain["entries"]:
        order_id = (link["order"] or {}).get("order_id")
        fill = link["fill"]
        print(f"    {link['ts']}  {link['status']:<18} "
              f"order_id={order_id or '—'}")
        if fill:
            print(f"        fill: qty={fill['filled_qty']} "
                  f"avg_price={fill['filled_avg_price']} at {fill['filled_at']}")

    replay = ledger_mod.replay_root(root, governor_thresholds,
                                    config_version=root["config_version"])
    print(f"\n  REPLAY of the decision that produced this order: "
          f"matched={replay['matched']}  differences={replay['differences'] or 'none'}")
    print(f"  The verdict behind a REAL position re-derives from the entry's own")
    print(f"  embedded proposal, account state and clock. That is the claim this")
    print(f"  whole system makes, checked against an order that actually exists.")
    return chain


# ---------------------------------------------------------------------------

def parse_qty(value):
    if value == "auto":
        return "auto"
    try:
        qty = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--qty takes a positive integer or 'auto', got {value!r}"
        ) from None
    if qty < 1:
        raise argparse.ArgumentTypeError("--qty must be at least 1")
    return qty


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env", default=".env", metavar="FILE",
        help="which env file to load, and therefore WHICH ACCOUNT this run is "
             "for. Defaults to .env (dev). config/profiles.json maps it to an "
             "account number, a ledger, a demo sample and a governor config.",
    )
    parser.add_argument(
        "--submit", action="store_true",
        help="after the run, SUBMIT the approved proposal as a REAL order on the "
             "selected account through the executor, and follow it to a terminal "
             "state. Off by default; requires a human to type it.",
    )
    parser.add_argument(
        "--qty", default=1, type=parse_qty, metavar="N|auto",
        help="lots for the passing proposal. 'auto' asks the GOVERNOR for the "
             "largest size it will approve — propose, read the max_loss_cap "
             "detail, step down until approved — rather than computing a cap "
             "here that would then exist in two places.",
    )
    args = parser.parse_args()

    profile = load_profile(args.env)

    # A submitted order with mode=approve but no approver would be a lie in the
    # ledger: shape 5's approved_by/approved_at would be null while the mode
    # claimed a human confirmed. Autopilot is the honest mode for an order the
    # governor alone gated, and it is what the scored run uses.
    mode = "autopilot" if args.submit else "approve"

    print(RULE)
    print("GlassBox RUN — live chain -> screener -> governor -> ledger")
    print(f"PROFILE: {profile['name'].upper()}   env={profile['env_file']}   "
          f"account={profile['account_number']}   "
          f"scored={'YES' if profile['scored'] else 'no'}")
    if profile["scored"]:
        print("*** THIS IS THE SCORED COMPETITION ACCOUNT. Its total equity at EOD")
        print("*** 2026-09-03 is the judged number. Every order goes through this")
        print("*** harness, under the governor. No manual orders, ever.")
    if args.submit:
        print("--submit IS SET: the approved proposal WILL be sent to this account")
        print("as a real order, in AUTOPILOT mode, through the executor.")
    else:
        print("NO ORDER SUBMISSION. The data session raises on any /orders path")
        print("and has no POST path at all.")
    print(RULE)

    load_dotenv(REPO / profile["env_file"])
    config = load_config()                     # paper guard fires here
    secrets = (config["api_key"], config["secret_key"])
    tunables = json.loads(DATAFEED_CONFIG.read_text(encoding="utf-8"))
    screener_thresholds = json.loads(SCREENER_THRESHOLDS.read_text(encoding="utf-8"))
    governor_thresholds = json.loads(
        profile["governor_thresholds"].read_text(encoding="utf-8")
    )
    config_version = content_hash(profile["governor_thresholds"])
    code_sha = code_version()

    # -- 0. WHO ARE WE TALKING TO -----------------------------------------
    # Before the chain, before the screener, before anything that costs time or
    # could become an order. The transport built here is the executor's, and it
    # is the one that would carry the trade.
    print(f"\n{THIN}\n0. ACCOUNT IDENTITY GUARD  (before anything else)\n{THIN}")
    transport = AlpacaPyTransport(config)      # paper guard fires in here too
    identity, equity, _ = confirm_account(transport, profile, config)
    print(f"  /v2/account      : account_number={identity['account_number']} "
          f"status={identity['broker_status']}")
    print(f"  expected         : {profile['account_number']}  -> MATCH")
    print(f"  trading base url : {identity['trading_base_url']}  (contains 'paper')")
    print(f"  equity           : {equity:,.2f}   — what every percentage cap on")
    print(f"                     this run resolves against")
    print(f"  ledger           : {profile['ledger'].relative_to(REPO)}")
    print(f"  governor config  : {profile['governor_thresholds'].relative_to(REPO)}")
    print(f"  config_version   : {config_version}")
    print(f"  code_version     : {code_sha}")

    session = NoOrdersSession()
    feed = DataFeed(config, session=session)

    # -- 1. the venue's clock and calendar --------------------------------
    print(f"\n{THIN}\n1. READ the venue's clock and calendar  (seam 6c)\n{THIN}")
    opened_at = feed.fetch_clock()
    read_start = parse_wire_ts(opened_at["timestamp"])
    lookback = tunables["calendar_lookback_days"]
    calendar = feed.fetch_calendar(
        (read_start.date() - timedelta(days=lookback)).isoformat(),
        (read_start.date() + timedelta(days=1)).isoformat(),
    )
    print(f"  /v2/clock        : is_open={opened_at['is_open']}  timestamp={opened_at['timestamp']}")
    print(f"  /v2/calendar     : {len(calendar)} sessions in the window")

    # -- 2. the chain ------------------------------------------------------
    print(f"\n{THIN}\n2. FETCH the chain\n{THIN}")
    today = date.today()
    gte = (today + timedelta(days=tunables["dte_min_days"])).isoformat()
    lte = (today + timedelta(days=tunables["dte_max_days"])).isoformat()

    # Clamp the fetch to the scored-run expiry bound, so a contract that the
    # governor would reject on x_max_expiry never enters the pipeline at all.
    # The bound has ONE owner — the governor config — and this reads it rather
    # than restating it, so the two cannot disagree.
    bound = governor_thresholds["max_expiry_date"]
    clamped = bound is not None and bound < lte
    if clamped:
        lte = bound

    contracts = feed.fetch_contracts(
        tunables["underlying"], expiration_date_gte=gte, expiration_date_lte=lte,
        as_of=read_start, limit=tunables["page_limit"],
    )
    symbols = [c["symbol"] for c in contracts["option_contracts"]]
    contracts_by_symbol = {c["symbol"]: c for c in contracts["option_contracts"]}
    snapshots = feed.fetch_snapshots(
        symbols, as_of=read_start, feed=tunables["snapshot_feed"],
        limit=tunables["page_limit"],
    )
    print(f"  DTE band         : {tunables['dte_min_days']}..{tunables['dte_max_days']} days "
          f"-> {gte} .. {lte}")
    if clamped:
        print(f"  CLAMPED to       : max_expiry_date={bound} (DECIDED) — scoring reads")
        print(f"                     total account equity at the bound, so nothing that")
        print(f"                     outlives it is fetched, let alone proposed")
    print(f"  contracts        : {len(symbols)} over {contracts['pages']} pages")
    print(f"  snapshots        : {len(snapshots['snapshots'])} over {snapshots['pages']} requests")

    # -- 2b. as_of, resolved when the read COMPLETED -----------------------
    clock = feed.fetch_clock()
    now = parse_wire_ts(clock["timestamp"])
    as_of = resolve_as_of(clock, calendar, now=now)
    contracts, snapshots = stamped(contracts, as_of), stamped(snapshots, as_of)
    print(f"  read window      : {read_start.isoformat()} .. {now.isoformat()} "
          f"({(now - read_start).total_seconds():.1f}s)")
    print(f"  as_of            : {as_of.isoformat()}"
          f"   ({'market open -> now, at the END of the read' if clock['is_open'] else 'market closed -> last close'})")
    print(f"  as_of on both    : {contracts['as_of']} / {snapshots['as_of']}")
    if not clock["is_open"]:
        print("  NOTE             : the market is CLOSED. Screening and proposing run")
        print("                     at any time (6c); order submission is what requires")
        print("                     market_open, and this run submits nothing.")

    # -- 3. screen ---------------------------------------------------------
    print(f"\n{THIN}\n3. SCREEN  (shape 6, fail closed)\n{THIN}")
    screened = screen_chain(contracts, snapshots, as_of=as_of,
                            thresholds=screener_thresholds)
    accepted, rejected = screened["accepted"], screened["rejected"]
    counts = {}
    for entry in rejected:
        for reason in entry["reasons"]:
            counts[reason] = counts.get(reason, 0) + 1
    print(f"  accepted         : {len(accepted)}")
    print(f"  rejected         : {len(rejected)}")
    print(f"  reason counts    : (a contract may carry more than one)")
    for reason, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"      {reason:<16} {count}")
    assert len(accepted) + len(rejected) == len(symbols), "a contract went missing"
    print(f"  every contract accounted for: {len(accepted)} + {len(rejected)} "
          f"= {len(symbols)}")

    spot, pairs, spread = estimate_spot(accepted, snapshots["snapshots"])
    if spot:
        print(f"  spot (put-call parity over {pairs} strike pairs): {spot:.2f} "
              f"[{spread[0]:.2f}..{spread[1]:.2f}] — strike selection only, no")
        print(f"                     decision depends on it")

    # -- 4. the proposals --------------------------------------------------
    print(f"\n{THIN}\n4. BUILD proposals from the ACCEPTED set\n{THIN}")
    # `null` / absent means no window is configured for this profile — the
    # honest value for a run that has not decided one, stated rather than left
    # as a silent pass, exactly as max_expiry_date and x_total_open_risk do it.
    window = governor_thresholds.get("liquidity_window")
    if window is None:
        print(f"  liquidity window : none configured for this profile — proposals are")
        print(f"                     built from the whole ACCEPTED set")
    else:
        print(f"  liquidity window : two_sided_quote={window['require_two_sided_quote']} "
              f"min_open_interest={window['min_open_interest']} "
              f"short_leg_abs_delta={window['short_leg_abs_delta_min']}"
              f"..{window['short_leg_abs_delta_max']}")

    report = {}

    def build_good(qty):
        return build_pass_vertical(accepted, snapshots["snapshots"],
                                   contracts_by_symbol, spot, width=5.0,
                                   window=window, qty=qty, report=report)

    probe = build_good(1)
    for label, count in sorted(report.items(), key=lambda kv: -kv[1]):
        print(f"      {label:<24} {count}")
    bad = build_reject_csp(accepted, snapshots["snapshots"], spot)
    if probe is None or bad is None:
        raise SystemExit(
            "no pair survived: the ACCEPTED set holds no 5-wide put vertical "
            "below spot whose legs both clear the liquidity window. The per-reason "
            "counts above say which test did the excluding. NOTHING WAS WRITTEN and "
            "no order was placed. Widen the window in config with a reason, or "
            "re-run when the chain is richer."
        )
    print(f"  (a) {probe['structure']}: {' / '.join(l['symbol'] for l in probe['legs'])}")
    print(f"  (b) {bad['structure']}: {' / '.join(l['symbol'] for l in bad['legs'])} "
          f"x{bad['qty']}  [deliberately bad]")

    # -- 5. account state and the composed view ----------------------------
    print(f"\n{THIN}\n5. ACCOUNT state  (2b RAW -> the governor's composed view)\n{THIN}")
    raw = feed.fetch_raw_account_state(as_of=as_of)
    dev = ledger_mod.Ledger(profile["ledger"])
    profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    existing = dev.read_entries()
    identity, equity, _ = confirm_account(transport, profile, config)
    view = compose_account_view(raw, existing, equity)
    print(f"  RAW (data layer) : cash={raw['cash']:.2f} buying_power={raw['buying_power']:.2f} "
          f"positions={raw['positions'] or '{}'}")
    print(f"                     fields={sorted(raw)}  — no reserved_* (A2 b)")
    print(f"  identity re-read : {identity['account_number']} equity={equity:,.2f} "
          f"(confirmed again AT decision time)")
    print(f"  ledger           : {profile['ledger'].relative_to(REPO)} — {len(existing)} entries, "
          f"{len(ledger_mod.list_roots(existing))} roots")
    print(f"  COMPOSED (gov)   : equity={view['equity']:,.2f} "
          f"reserved_cash={view['reserved_cash']:.2f} "
          f"open_positions={view['ledger']['open_positions'] or '{}'}")
    print(f"                     open_risk={view['ledger']['open_risk']}")

    snapshot = {"account_state": view, "clock": clock,
                "account_identity": identity}

    def run_governor(proposal):
        return govern(proposal, view, clock, thresholds=governor_thresholds,
                      mode=mode, config_version=config_version)

    # -- 6. govern ---------------------------------------------------------
    if args.qty == "auto":
        print(f"\n{THIN}\n6. SIZE by asking the governor, then GOVERN\n{THIN}")
        good, verdict_good, attempts = size_by_asking_the_governor(
            build_good, run_governor
        )
        for qty, attempt in attempts:
            failed = failing_rules(attempt)
            print(f"  qty={qty:<3} -> {'APPROVED' if attempt['approved'] else 'rejected'}"
                  f"  {'' if attempt['approved'] else 'on ' + ', '.join(failed)}")
            fields = detail_fields(detail_for(attempt, "max_loss_cap"))
            print(f"          max_loss_cap: computed_max_loss={fields.get('computed_max_loss')} "
                  f"cap={fields.get('cap')} {fields.get('cap_basis', '')}")
        print(f"  chosen qty       : {good['qty']}  — the largest the GOVERNOR "
              f"approved, not a size computed here")
    else:
        good = build_good(args.qty)
        verdict_good = run_governor(good)
    verdict_bad = run_governor(bad)

    show_verdict("6a. PROPOSAL (a) — the one that should PASS", good, verdict_good)
    show_verdict("6b. PROPOSAL (b) — the one that MUST be REJECTED", bad, verdict_bad)

    # The adversarial half is not allowed to be a near miss. If this ever passes,
    # the run stops before writing anything and the governor has a real defect.
    if verdict_bad["approved"]:
        raise SystemExit(
            "STOP: the deliberately bad proposal was APPROVED. Nothing has been "
            "written to any ledger. This is a governor defect, not a bad run."
        )
    failed_good = failing_rules(verdict_good)
    if failed_good and failed_good != ["market_open"]:
        print(f"\n  STOP: proposal (a) was REJECTED on {', '.join(failed_good)}.")
        print(f"  Its checks are printed above in full. NOTHING has been written to")
        print(f"  any ledger and NO order was placed. A governed refusal is the")
        print(f"  system working; it is reported, not worked around.")
        return 2
    if failed_good == ["market_open"]:
        print(f"\n  NOTE on (a): every risk check PASSED. The single failing check is")
        print(f"  market_open, because the market is closed right now — which is 6c")
        print(f"  behaving exactly as designed: screening and proposing run at any")
        print(f"  time, and submission is what is gated. Re-run inside a session and")
        print(f"  this verdict is APPROVED with no other change.")
        if args.submit:
            print(f"\n  STOP: --submit was set but the market is closed, so the")
            print(f"  governor has not approved this proposal and the executor will")
            print(f"  not be handed an unapproved verdict. Nothing was written.")
            return 2

    # -- 7. ledger ---------------------------------------------------------
    print(f"\n{THIN}\n7. LEDGER  (append-only, root entries, pre-submission)\n{THIN}")
    keep = ("account_number",) if profile["scored"] else ()
    mirror = DemoMirror(profile["demo_sample"], secrets, keep=keep)
    ts = datetime.now(timezone.utc)
    root_good = write_root(dev, mirror, ts=ts, as_of=as_of, proposal=good,
                           verdict=verdict_good, snapshot=snapshot,
                           config_version=config_version, code_sha=code_sha)
    root_bad = write_root(dev, mirror, ts=ts, as_of=as_of, proposal=bad,
                          verdict=verdict_bad, snapshot=snapshot,
                          config_version=config_version, code_sha=code_sha)

    print(f"  {profile['ledger'].relative_to(REPO)}  (gitignored)  +2 root entries")
    print(f"  {profile['demo_sample'].relative_to(REPO)}  (committed)   +2 scrubbed entries")
    print(f"  fields dropped for the demo copy: {mirror.dropped_total}")
    if mirror.kept:
        print(f"  fields KEPT deliberately: {', '.join(mirror.kept)} — the competition")
        print(f"  account id is a required submission disclosure, and an identifier is")
        print(f"  not a credential. The credential scan ran over every byte regardless.")
    for entry in (root_good, root_bad):
        print(f"    id={entry['id']}  status={entry['status']}  root_id={entry['root_id']} "
              f"order={entry['order']} fill={entry['fill']}")

    # -- 8. fold and replay ------------------------------------------------
    print(f"\n{THIN}\n8. FOLD the chains, and REPLAY both decisions\n{THIN}")
    entries = dev.read_entries()
    for entry in (root_good, root_bad):
        chain = ledger_mod.fold_chain(entries, entry["id"])
        status, terminal = ledger_mod.current_status(entries, entry["id"])
        print(f"  chain {entry['id']}")
        print(f"    entries={len(chain['entries'])} status={status} terminal={terminal}")
        for link in chain["entries"]:
            print(f"      {link['ts']}  {link['status']:<18} root_id={link['root_id']}")
        result = ledger_mod.replay_root(entry, governor_thresholds,
                                        config_version=entry["config_version"])
        print(f"    REPLAY matched={result['matched']}  differences="
              f"{result['differences'] or 'none'}")
        if not result["matched"]:
            raise SystemExit("a recorded verdict does not follow from its own inputs")
        print(f"    -> the recorded verdict was re-derived from the entry's OWN "
              f"embedded proposal,")
        print(f"       account state and clock, under the config it names. Nothing "
              f"else was consulted.")

    if args.submit:
        submit_for_real(dev, mirror, root_good, config, profile, transport,
                        governor_thresholds)

    print(f"\n{RULE}")
    print(f"RUN COMPLETE on the {profile['name'].upper()} account "
          f"({profile['account_number']}).")
    print(f"{session.count} GET requests through the data session, which cannot "
          f"reach an orders endpoint.")
    # The CURRENT status of each chain, not the status the root was written
    # with: after a submission the root says approved_pending forever — that is
    # append-only working — and the chain is what moved.
    final = dev.read_entries()
    for label, root in (("a", root_good), ("b", root_bad)):
        status, terminal = ledger_mod.current_status(final, root["id"])
        print(f"  ({label}) {status:<18} {root['id']}  terminal={terminal}")
    print(f"Both replay identically.")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
