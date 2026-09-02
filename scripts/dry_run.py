#!/usr/bin/env python3
"""End-to-end run: live chain -> screener -> governor -> ledger [-> a real order].

The point of this script is that it is the whole pipeline, running for real, on
real data, against the real DEV paper account. Without it, GlassBox is five
green contract suites and a claim.

**By default it stops one step short of the broker.** Every request the data
path makes goes through a session that raises on any URL containing `/orders`
and has no POST method at all, so a dry run cannot submit even by accident. That
guard is printed at the top of the run rather than asserted in a comment.

**With `--submit` it goes the last step**, and submits the approved proposal as
a REAL order on the DEV paper account through `glassbox.executor` and Alpaca's
official SDK. That flag exists so the decision is a human typing it, never a
default. When it is set the run switches to **autopilot** mode: a submitted
order recorded as `approve` with `approved_by` null would be a ledger entry
claiming a human confirmed something nobody confirmed.

What it does, in order:

  1. Resolve `as_of` from the LIVE `/v2/clock` and `/v2/calendar` (seam 6c),
     taken when the read COMPLETED, not when it started.
  2. Fetch the SPY chain inside the configured DTE band — clamped to the scored
     run's `max_expiry_date` — and its snapshots.
  3. Screen it (shape 6). Fail-closed rejections are counted by reason.
  4. Build TWO proposals from the ACCEPTED set with a small helper:
       (a) a defined-risk vertical priced off real bids and asks, which should
           PASS every check;
       (b) a deliberately bad cash-secured put — over-sized, with a
           `claimed_max_loss` a fraction of the real figure — which MUST be
           rejected, on the arithmetic rather than on the claim.
  5. Fetch RAW account state (2b RAW) and compose the governor's view against
     the current dev ledger (A2 b: reservations are ledger-derived).
  6. Govern both. The run STOPS, having written nothing, if the bad one is
     approved or the good one fails on anything but `market_open`.
  7. Append both root entries to `data/ledger_dev.jsonl` (gitignored) and a
     scrubbed copy to `demo/ledger_sample.jsonl` (committed — the demo's hero
     artefact).
  8. Print both verdicts with full `checks[]` detail, the folded chains, and a
     REPLAY of each root proving the recorded verdict follows from the recorded
     inputs.
  9. With `--submit`: hand the approved root to the executor, follow the order
     to a terminal state, and append `submitted` / `filled` / `partial_fill` /
     `broker_rejected` follow-ups chained on its `root_id` (5a).

Usage:
    python scripts/dry_run.py              # no order can be placed
    python scripts/dry_run.py --submit     # places ONE real order on DEV
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
# The SCORED-RUN governor config, not the suite's frozen golden reference. It
# carries the DECIDED max_expiry_date; see its own _max_expiry_rationale.
GOVERNOR_THRESHOLDS = REPO / "config" / "thresholds.governor.SCORED.json"

DEV_LEDGER = REPO / "data" / "ledger_dev.jsonl"
DEMO_LEDGER = REPO / "demo" / "ledger_sample.jsonl"

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
                f"the dry run tried to reach an orders endpoint: {url}. Nothing "
                f"in this pipeline may submit; the executor does not exist yet"
            )
        self.count += 1
        return self._inner.get(url, **kwargs)

    def post(self, *args, **kwargs):
        raise AssertionError(
            "the dry run does not write to the broker. There is no POST path in "
            "this pipeline, by construction"
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
# The governor's composed account view (A2 b), derived from the ledger
# ---------------------------------------------------------------------------

def compose_account_view(raw, entries):
    """Raw broker state + ledger-derived reservations = the governor's view (2b).

    NOTE for both humans: A2(b) assigns this composition to the GOVERNOR, and it
    belongs in `glassbox/governor.py` with GB-C criteria of its own. It lives
    here for now because promoting it would add uncovered code to a module whose
    suite is already armed; that promotion is the follow-up, not this commit.

    A commitment is live if its chain has not reached a terminal state. Reserving
    against terminal chains would double-count a position that is already closed
    or was never opened; not reserving against in-flight ones is how two
    cash-secured puts claim the same collateral.
    """
    view = {
        "as_of": raw["as_of"],
        "cash": raw["cash"],
        "buying_power": raw["buying_power"],
        "reserved_cash": 0.0,
        "positions": {
            symbol: {"shares": position["shares"], "reserved_shares": 0}
            for symbol, position in raw["positions"].items()
        },
        # PROPOSED (carried in my 10:55 block, amendment 3): 2b's composed view
        # does not print this block, but churn_guard and x_position_cap are
        # ledger-derived and fail closed without it.
        "ledger": {"open_positions": {}, "recent_activity": {}},
    }

    for root in ledger_mod.list_roots(entries):
        status, terminal = ledger_mod.current_status(entries, root["id"])
        if terminal:
            continue
        proposal = root.get("proposal") or {}
        underlying = proposal.get("underlying")
        structure = proposal.get("structure")
        qty = proposal.get("qty", 0)
        if not underlying:
            continue

        if structure == "cash_secured_put":
            view["reserved_cash"] += proposal["legs"][0]["strike"] * 100 * qty
        elif structure == "covered_call":
            position = view["positions"].setdefault(
                underlying, {"shares": 0, "reserved_shares": 0}
            )
            position["reserved_shares"] += 100 * qty

        counts = view["ledger"]["open_positions"]
        counts[underlying] = counts.get(underlying, 0) + 1
        activity = view["ledger"]["recent_activity"].setdefault(underlying, {})
        opened = root["ts"]
        if opened > activity.get("last_open_at", ""):
            activity["last_open_at"] = opened
            activity["position_opened_at"] = opened

    return view


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


def build_pass_vertical(accepted, snapshots, spot, width):
    """A defined-risk put vertical, priced off real bids and asks.

    Sold at the BID and bought at the ASK — the side of the spread a taker
    actually gets. Pricing a proposal at the mid makes it look better than it is,
    which is the sort of small dishonesty this whole project exists to refuse.

    Chosen: the widest-premium `width`-wide pair below spot whose legs are both in
    the ACCEPTED set. The governor recomputes everything about it from scratch.
    """
    puts = sorted(
        (c for c in accepted
         if c["option_type"] == "put" and (spot is None or c["strike"] < spot)),
        key=lambda c: (c["expiry"], c["strike"]),
    )
    by_key = {(c["expiry"], c["strike"]): c for c in puts}

    best = None
    for short in puts:
        long_leg = by_key.get((short["expiry"], short["strike"] - width))
        if long_leg is None:
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
            continue
        if best is None or net < best[0]:
            best = (net, legs, short, long_leg)
    if best is None:
        return None
    net, legs, short, long_leg = best

    # The governor computes max loss itself; these are the strategist's stated
    # belief and are ADVISORY (2d). They are stated HONESTLY here so that the
    # only dishonest proposal in this run is the one that is meant to be.
    credit = -net if net < 0 else 0.0
    claimed_max_loss = round((width - credit) * 100, 2) if net < 0 else round(net * 100, 2)
    claimed_max_gain = round(credit * 100, 2) if net < 0 else round((width - net) * 100, 2)
    return {
        "underlying": "SPY",
        "structure": "vertical_spread",
        "qty": 1,
        "legs": legs,
        "net_debit_credit": net,
        "rationale": (
            f"Defined-risk {width:.0f}-wide SPY put vertical expiring "
            f"{short['expiry']}: short the {short['strike']:.0f}, long the "
            f"{long_leg['strike']:.0f}. Risk is capped at the width of the wings "
            f"whatever SPY does. Priced at the bid on the short leg and the ask "
            f"on the long leg — the side a taker actually gets. Hand-authored for "
            f"this dry run; no strategist and no LLM was involved."
        ),
        "claimed_max_loss": claimed_max_loss,
        "claimed_max_gain": claimed_max_gain,
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
            f"the dry run. The position is larger than the account can secure and "
            f"the stated max loss is a fiction."
        ),
        "claimed_max_loss": 250.00,
        "claimed_max_gain": round(-net_of(legs) * 100 * qty, 2),
    }


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

#: Nothing in a shape 5 root entry should carry account identity — the composed
#: account view is balances and share counts, not an account number. The demo
#: copy drops these anyway and REPORTS how many it dropped, so "scrubbed" is a
#: measured fact rather than a promise.
_DEMO_SCRUB = ("account_number", "account_id", "email", "owner", "api_key")


def scrub_for_demo(entry, secrets):
    dropped = []

    def walk(value, path=""):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in _DEMO_SCRUB:
                    dropped.append(f"{path}.{key}".lstrip("."))
                    continue
                out[key] = walk(item, f"{path}.{key}")
            return out
        if isinstance(value, list):
            return [walk(item, f"{path}[]") for item in value]
        return value

    scrubbed = walk(entry)
    text = json.dumps(scrubbed)
    for secret in secrets:
        if secret and len(secret) >= 12 and secret in text:
            raise SystemExit("ABORT: a credential reached a ledger entry. Stop.")
    return scrubbed, dropped


def mirror_to_demo(entry, secrets):
    """Append one entry to the committed demo ledger, scrubbed and checked."""
    scrubbed, dropped = scrub_for_demo(entry, secrets)
    with DEMO_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(ledger_mod.serialize(scrubbed) + "\n")
    return dropped


def write_root(dev, demo_lines, *, ts, as_of, proposal, verdict, snapshot,
               config_version, code_sha, secrets):
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
    scrubbed, dropped = scrub_for_demo(entry, secrets)
    demo_lines.append((ledger_mod.serialize(scrubbed), dropped))
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


def submit_for_real(dev, root, config, secrets, governor_thresholds):
    """Submit the approved root as a REAL order, and follow it to a terminal state.

    This is the only function in the repo that causes a position to exist. It
    runs solely because a human typed --submit.

    Everything it needs was decided before it was called: the proposal was
    screened from live data, the governor approved it on its own arithmetic, and
    the root entry is already on disk with the id that the order's
    `client_order_id` embeds. This function adds no judgement of its own — it
    hands the entry to the executor and writes down what the broker says.
    """
    print(f"\n{RULE}\n9. SUBMIT — a real order on the DEV paper account\n{RULE}")

    transport = AlpacaPyTransport(config)      # paper guard fires in here too
    executor = Executor(ledger=dev, transport=transport, config=config,
                        env=os.environ)

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
    mirror_to_demo(result["entry"], secrets)
    order = result["order"]
    print(f"\n  SUBMITTED.")
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
            mirror_to_demo(entry, secrets)
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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--submit", action="store_true",
        help="after the dry run, SUBMIT the approved proposal as a REAL order on "
             "the DEV paper account through the executor, and follow it to a "
             "terminal state. Off by default; requires a human to type it.",
    )
    args = parser.parse_args()

    # A submitted order with mode=approve but no approver would be a lie in the
    # ledger: shape 5's approved_by/approved_at would be null while the mode
    # claimed a human confirmed. Autopilot is the honest mode for an order the
    # governor alone gated, and it is what the scored run uses.
    mode = "autopilot" if args.submit else "approve"

    print(RULE)
    print("GlassBox DRY RUN — live chain -> screener -> governor -> ledger")
    if args.submit:
        print("--submit IS SET: the approved proposal WILL be sent to the DEV paper")
        print("account as a real order, in AUTOPILOT mode, through the executor.")
    else:
        print("NO ORDER SUBMISSION. The data session raises on any /orders path")
        print("and has no POST path at all.")
    print(RULE)

    load_dotenv(REPO / ".env")
    config = load_config()                     # paper guard fires here
    secrets = (config["api_key"], config["secret_key"])
    tunables = json.loads(DATAFEED_CONFIG.read_text(encoding="utf-8"))
    screener_thresholds = json.loads(SCREENER_THRESHOLDS.read_text(encoding="utf-8"))
    governor_thresholds = json.loads(GOVERNOR_THRESHOLDS.read_text(encoding="utf-8"))
    config_version = content_hash(GOVERNOR_THRESHOLDS)
    code_sha = code_version()

    session = NoOrdersSession()
    feed = DataFeed(config, session=session)
    print(f"\n  trading base url : {config['trading_base_url']}  (contains 'paper')")
    print(f"  config_version   : {config_version}")
    print(f"  code_version     : {code_sha}")

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

    # -- 4. two proposals --------------------------------------------------
    print(f"\n{THIN}\n4. BUILD two proposals from the ACCEPTED set\n{THIN}")
    good = build_pass_vertical(accepted, snapshots["snapshots"], spot, width=5.0)
    bad = build_reject_csp(accepted, snapshots["snapshots"], spot)
    if good is None or bad is None:
        raise SystemExit(
            "the accepted set did not contain the contracts these two proposals "
            "need. Nothing was written. Re-run when the chain is richer."
        )
    print(f"  (a) {good['structure']}: {' / '.join(l['symbol'] for l in good['legs'])}")
    print(f"  (b) {bad['structure']}: {' / '.join(l['symbol'] for l in bad['legs'])} "
          f"x{bad['qty']}  [deliberately bad]")

    # -- 5. account state and the composed view ----------------------------
    print(f"\n{THIN}\n5. ACCOUNT state  (2b RAW -> the governor's composed view)\n{THIN}")
    raw = feed.fetch_raw_account_state(as_of=as_of)
    dev = ledger_mod.Ledger(DEV_LEDGER)
    DEV_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    existing = dev.read_entries()
    view = compose_account_view(raw, existing)
    print(f"  RAW (data layer) : cash={raw['cash']:.2f} buying_power={raw['buying_power']:.2f} "
          f"positions={raw['positions'] or '{}'}")
    print(f"                     fields={sorted(raw)}  — no reserved_* (A2 b)")
    print(f"  dev ledger       : {DEV_LEDGER.relative_to(REPO)} — {len(existing)} entries, "
          f"{len(ledger_mod.list_roots(existing))} roots")
    print(f"  COMPOSED (gov)   : reserved_cash={view['reserved_cash']:.2f} "
          f"open_positions={view['ledger']['open_positions'] or '{}'}")

    snapshot = {"account_state": view, "clock": clock}

    # -- 6. govern ---------------------------------------------------------
    verdict_good = govern(good, view, clock, thresholds=governor_thresholds,
                          mode=mode, config_version=config_version)
    verdict_bad = govern(bad, view, clock, thresholds=governor_thresholds,
                         mode=mode, config_version=config_version)
    show_verdict("6a. PROPOSAL (a) — the one that should PASS", good, verdict_good)
    show_verdict("6b. PROPOSAL (b) — the one that MUST be REJECTED", bad, verdict_bad)

    # The adversarial half is not allowed to be a near miss. If this ever passes,
    # the run stops before writing anything and the governor has a real defect.
    if verdict_bad["approved"]:
        raise SystemExit(
            "STOP: the deliberately bad proposal was APPROVED. Nothing has been "
            "written to any ledger. This is a governor defect, not a bad run."
        )
    failed_good = [c["rule"] for c in verdict_good["checks"] if not c["passed"]]
    if failed_good and failed_good != ["market_open"]:
        raise SystemExit(
            f"STOP: proposal (a) failed on {failed_good}. It is built to pass "
            f"every risk check; a failure here is a finding, not a bad run."
        )
    if failed_good == ["market_open"]:
        print(f"\n  NOTE on (a): every risk check PASSED. The single failing check is")
        print(f"  market_open, because the market is closed right now — which is 6c")
        print(f"  behaving exactly as designed: screening and proposing run at any")
        print(f"  time, and submission is what is gated. Re-run inside a session and")
        print(f"  this verdict is APPROVED with no other change.")

    # -- 7. ledger ---------------------------------------------------------
    print(f"\n{THIN}\n7. LEDGER  (append-only, root entries, pre-submission)\n{THIN}")
    ts = datetime.now(timezone.utc)
    demo_lines = []
    root_good = write_root(dev, demo_lines, ts=ts, as_of=as_of, proposal=good,
                           verdict=verdict_good, snapshot=snapshot,
                           config_version=config_version, code_sha=code_sha,
                           secrets=secrets)
    root_bad = write_root(dev, demo_lines, ts=ts, as_of=as_of, proposal=bad,
                          verdict=verdict_bad, snapshot=snapshot,
                          config_version=config_version, code_sha=code_sha,
                          secrets=secrets)
    dropped_total = sum(len(dropped) for _, dropped in demo_lines)
    with DEMO_LEDGER.open("a", encoding="utf-8") as fh:
        for line, _ in demo_lines:
            fh.write(line + "\n")

    print(f"  {DEV_LEDGER.relative_to(REPO)}  (gitignored)  +2 root entries")
    print(f"  {DEMO_LEDGER.relative_to(REPO)}  (committed)   +2 scrubbed entries")
    print(f"  fields scrubbed for the demo copy: {dropped_total} — a shape 5 entry "
          f"carries balances,")
    print(f"  not account identity, so there is nothing in it to remove. That is a "
          f"property of the")
    print(f"  seam, and this line is the check that it still holds.")
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
        submit_for_real(dev, root_good, config, secrets, governor_thresholds)

    print(f"\n{RULE}")
    print(f"DRY RUN COMPLETE. {session.count} GET requests through the data session,")
    print(f"which cannot reach an orders endpoint.")
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
