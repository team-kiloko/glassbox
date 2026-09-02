#!/usr/bin/env python3
"""ONE governed cycle: resolve as_of -> screen -> propose -> govern -> execute -> record.

This is the unit `scripts/run_session.py` repeats. It runs once and exits, and
it is the same code path either way: a session is not a different program, it is
this one called again.

**What a cycle is.** Ask the broker who it is; read the venue's clock; if the
market is closed, stop; fetch the chain inside the configured DTE band clamped to
the scored expiry bound; screen it; build candidate proposals; compose the
governor's account view from the ledger; govern; write the decision down; and if
the governor approved, submit through the executor and follow the order to a
terminal state, appending each transition to the chain.

**What a cycle is not.** It holds no risk opinion of its own. Every number that
could refuse a trade lives in the governor's config and is enforced by the
governor; nothing here can loosen one, and the only thing this file decides is
*whether it is worth spending a cycle at all*. There are exactly two such
decisions and both fail closed:

  * **A closed market ends the cycle before the chain is fetched.** The
    governor's `market_open` check remains the gate on any order that is
    actually proposed (6c) — but a loop that fetches, screens, proposes and
    governs its way to a foregone refusal every quarter of an hour would fill a
    scored account's ledger with noise, and the ledger is a submission artefact.
  * **A root id already on the ledger is not re-decided.** See below.

**At most one order per cycle.** Candidates are governed in order and the first
approved one is submitted; the rest are not governed at all. A cycle composes
ONE account view, and acting on a second approval would be acting on a view the
first order had already invalidated. The next cycle re-composes and re-asks.

**Idempotency, which is the property with money attached.** A loop is the first
component in this system that can make the same decision twice. Two things stop
that becoming two positions, and the runner relies on both:

  1. The ledger root id is content-hashed over the proposal and the config
     (`dry_run.entry_id`). A cycle re-run on the same second with the same
     proposal computes the same id, finds it already on the ledger, and
     re-decides nothing: no append, no submission, and it reports the order that
     already exists.
  2. `client_order_id` is `ORDER_ID_PREFIX + the root entry id` (shape 4), so
     even if it did resubmit, the broker refuses the duplicate rather than
     opening a second position — and the executor resolves that refusal to the
     existing order.

**Everything is injected.** The venue, the broker, the ledger, the clock and even
`sleep` arrive on a `RunContext`. That is what lets GB-R drive a whole cycle
against a venue that never existed, which is the only way to test what this does
on a closed market, at a cap, or against a broker claiming to be another account.

Usage:
    python scripts/run_cycle.py --env .env                  # one cycle, DEV
    python scripts/run_cycle.py --env .env --no-submit      # decide, record, stop
    python scripts/run_cycle.py --env .env.competition      # one cycle, SCORED
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

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
from glassbox.governor import compose_account_view, govern  # noqa: E402
from glassbox.ledger import iso_utc  # noqa: E402
from glassbox.screener import screen_chain  # noqa: E402

# The harness is imported, never copied. `build_pass_vertical`,
# `size_by_asking_the_governor`, `entry_id`, `confirm_account` and the rest were
# written for the one-shot run and are already covered by the day's real orders;
# a second copy of any of them here would be a second place for a tunable to
# live, which is exactly what CLAUDE.md forbids. The proposal helper in
# particular is a hand-authored stand-in and says so in its own rationale text —
# see `build_candidates` below, which is the seam a real strategist replaces.
from dry_run import (  # noqa: E402
    DemoMirror,
    build_pass_vertical,
    code_version,
    confirm_account,
    content_hash,
    entry_id,
    estimate_spot,
    failing_rules,
    load_profile,
    size_by_asking_the_governor,
)

#: The loop's own tunables. Not a risk limit: every one of those is the
#: governor's, and nothing in this file can loosen one.
RUNNER_CONFIG = REPO / "config" / "runner.PROPOSED.json"
DATAFEED_CONFIG = REPO / "config" / "datafeed.PROPOSED.json"
SCREENER_THRESHOLDS = REPO / "tests" / "fixtures" / "thresholds.PROPOSED.json"

#: The width of the vertical the stand-in proposal helper builds. Not a trading
#: judgement — it is the width the day's real orders used, kept so the runner
#: proposes the same shape the harness did rather than a new one nobody has seen.
_WIDTH = 5.0


class RunContext:
    """Everything one cycle needs, resolved once and reused by every cycle.

    Built by :func:`build_context` for a real run, and by GB-R directly over
    fakes. Nothing in here is discovered at cycle time: a component that reaches
    out and builds its own transport can only ever be tested against the thing
    it reaches.
    """

    def __init__(self, *, profile, config, governor_thresholds,
                 screener_thresholds, datafeed_tunables, runner, config_version,
                 code_version, mode, submit, feed, transport, ledger,
                 mirror=None, sleep=time.sleep):
        self.profile = profile
        self.config = config
        self.governor_thresholds = governor_thresholds
        self.screener_thresholds = screener_thresholds
        self.datafeed_tunables = datafeed_tunables
        self.runner = runner
        self.config_version = config_version
        self.code_version = code_version
        self.mode = mode
        self.submit = submit
        self.feed = feed
        self.transport = transport
        self.ledger = ledger
        self.mirror = mirror
        self.sleep = sleep

    def record(self, entry):
        """Mirror an entry into the committed demo sample, if there is one."""
        if self.mirror is not None:
            self.mirror.append(entry)
        return entry


# ---------------------------------------------------------------------------
# The strategist seam
# ---------------------------------------------------------------------------

def build_candidates(*, accepted, snapshots, contracts_by_symbol, spot,
                     governor_thresholds, run_governor, report=None):
    """Proposals for this cycle to govern, best first. **THE STRATEGIST SEAM.**

    Args:
        accepted: the screener's accepted list (shape 6), already shaped to drop
            into shape 2 `legs[]`.
        snapshots: `{symbol: snapshot}` for those contracts.
        contracts_by_symbol: the raw contract records, for `open_interest`.
        spot: an estimate, for strike selection only. No decision depends on it.
        governor_thresholds: the governor's config. Read here ONLY for
            `liquidity_window`, which narrows the candidate set — narrowing is a
            strategist's job, not a risk gate's. Nothing here reads a cap.
        run_governor: `proposal -> verdict`. Passed so a rules-based builder can
            SIZE by asking the governor rather than by computing a cap a second
            time. A strategist that does not size may ignore it entirely.
        report: optional counter mapping, for the per-reason exclusion counts.

    Returns:
        A list of shape-2 proposals, best first. The caller governs them; this
        function's verdicts, if it took any, are advisory to itself.

    **This implementation is a hand-authored stand-in, not a strategist.** It
    builds one defined-risk put vertical off real bids and asks, narrowed to the
    config's liquidity window, and sizes it by asking the governor. No LLM is
    involved and its `rationale` says so.

    **Replacing it is the whole MCP strategist integration.** A strategist that
    returns a list of shape-2 proposals from this signature plugs in with no
    change to anything downstream, because the governor recomputes every number
    it is handed and reads `claimed_max_loss` only to record how wrong it was.
    A proposal that arrives here from a language model is governed by exactly the
    same checks, on exactly the same arithmetic, as one that arrives from this.
    """
    window = governor_thresholds.get("liquidity_window")
    counts = {} if report is None else report

    def build(qty):
        return build_pass_vertical(accepted, snapshots, contracts_by_symbol, spot,
                                   width=_WIDTH, window=window, qty=qty,
                                   report=counts)

    if build(1) is None:
        return []
    sized, _verdict, _attempts = size_by_asking_the_governor(build, run_governor)
    return [sized]


# ---------------------------------------------------------------------------
# One cycle
# ---------------------------------------------------------------------------

def run_cycle(context, *, cycle_id, now):
    """Run one cycle and return what it did. See the module docstring.

    Args:
        context: a :class:`RunContext`.
        cycle_id: this cycle's label, e.g. ``"0007"``. Appears in the log line
            and nowhere else — the ledger's ids are content-hashed and do not
            depend on how many times the loop has been round.
        now: timezone-aware datetime this cycle is stamped with. The ROOT entry's
            `ts` is exactly this, which is what makes a re-run on the same second
            compute the same root id and therefore decide nothing.

    Returns:
        A mapping describing the cycle. :func:`format_cycle_line` renders it.

    Raises:
        Anything the venue, the broker or the executor raises. A cycle does NOT
        swallow its own failures: deciding whether one raised cycle is a
        transient or a fault is the session loop's job, and a cycle that
        returned a tidy result on a broken venue would take that decision away
        from it. The one exception is an account identity failure, which is not
        a transient in anybody's judgement and stops the session at once.
    """
    result = {
        "cycle_id": cycle_id,
        "as_of": None,
        "market_open": None,
        "account_number": None,
        "screened": {"accepted": 0, "rejected": 0},
        "candidates": 0,
        "approved": 0,
        "roots": [],
        "rejections": [],
        "order_id": None,
        "order_status": None,
        "submitted": 0,
        "skipped": None,
    }

    profile, tunables = context.profile, context.datafeed_tunables

    # -- 0. who are we talking to -----------------------------------------
    # Every cycle, before anything costs time. Once per session is not enough:
    # a session runs for hours unattended, the guard is cheap, and an order on
    # the wrong one of two indistinguishable paper accounts cannot be taken back.
    identity, equity, _ = confirm_account(context.transport, profile, context.config)
    result["account_number"] = identity["account_number"]

    # -- 1. the venue's clock, and the as_of everything is measured against --
    clock = context.feed.fetch_clock()
    read_at = parse_wire_ts(clock["timestamp"])
    calendar = context.feed.fetch_calendar(
        (read_at.date() - timedelta(days=tunables["calendar_lookback_days"])).isoformat(),
        (read_at.date() + timedelta(days=1)).isoformat(),
    )
    as_of = resolve_as_of(clock, calendar, now=read_at)
    result["as_of"] = iso_utc(as_of)
    result["market_open"] = bool(clock["is_open"])

    if not clock["is_open"]:
        # Fails closed, and stops here. Nothing is fetched, nothing is proposed,
        # nothing is written. The `as_of` above is still reported, so the log
        # line says WHEN it declined rather than only that it did.
        result["skipped"] = "market_closed"
        return result

    # -- 2. the chain, clamped to the scored expiry bound -------------------
    # The band is measured from `as_of`, never from the wall clock: `as_of` is
    # the timestamp every other step in this cycle is measured against, and a
    # fetch window derived from a second source of "today" could disagree with it.
    reference = as_of.date()
    gte = (reference + timedelta(days=tunables["dte_min_days"])).isoformat()
    lte = (reference + timedelta(days=tunables["dte_max_days"])).isoformat()
    bound = context.governor_thresholds["max_expiry_date"]
    if bound is not None and bound < lte:
        # ONE owner for the scored bound — the governor config — read here rather
        # than restated, so a contract the governor would refuse on x_max_expiry
        # never enters the pipeline at all.
        lte = bound

    contracts = context.feed.fetch_contracts(
        tunables["underlying"], expiration_date_gte=gte, expiration_date_lte=lte,
        as_of=as_of, limit=tunables["page_limit"],
    )
    symbols = [c["symbol"] for c in contracts["option_contracts"]]
    if not symbols:
        result["skipped"] = "empty_chain"
        return result
    snapshots = context.feed.fetch_snapshots(
        symbols, as_of=as_of, feed=tunables["snapshot_feed"],
        limit=tunables["page_limit"],
    )

    # -- 3. screen (shape 6, fail closed) ----------------------------------
    screened = screen_chain(contracts, snapshots, as_of=as_of,
                            thresholds=context.screener_thresholds)
    accepted, rejected = screened["accepted"], screened["rejected"]
    result["screened"] = {"accepted": len(accepted), "rejected": len(rejected)}

    # -- 3b. has this cycle already run? -----------------------------------
    # A cycle's identity is the CYCLE, not the proposal it happens to arrive at:
    # two cycles stamped with the same `now`, on the same account, under the same
    # config, are the same cycle. Root ids are content-hashed but PREFIXED with
    # that timestamp (`dry_run.entry_id`), so a re-run is recognisable from the
    # ledger alone, before anything is decided.
    #
    # Keying on the proposal instead would not work, and it is worth saying why:
    # by the time a re-run has re-derived its proposal the ledger has moved —
    # the first run's position is on the book — so the sizing search returns a
    # different quantity, the content hash differs, and the guard never fires.
    # The re-run would then correctly be refused on `churn_guard`, but it would
    # have written a second root to say so, and "correct by accident" is not a
    # property to rely on with an order at the end of it.
    #
    # The granularity is one second, which is the granularity of the id scheme.
    # Two genuinely different cycles inside one second would collide; the
    # interval is 900 seconds, and a repeat inside the same second is exactly
    # the case this exists for.
    existing = context.ledger.read_entries()
    cycle_key = now.strftime("%Y%m%dT%H%M%SZ") + "-"
    already = [root for root in ledger_mod.list_roots(existing)
               if root["id"].startswith(cycle_key)]
    if already:
        result["skipped"] = "idempotent"
        result["roots"] = [{"id": root["id"], "status": "already_recorded",
                            "approved": root["verdict"]["approved"], "failed": []}
                           for root in already]
        for root in already:
            order_id = _order_id_of(existing, root["id"])
            if order_id:
                result["order_id"] = order_id
                result["order_status"] = ledger_mod.current_status(
                    existing, root["id"])[0]
                break
        return result

    # -- 4. the composed account view (A2 b) -------------------------------
    raw = context.feed.fetch_raw_account_state(as_of=as_of)
    view = compose_account_view(raw, existing, equity)
    snapshot = {"account_state": view, "clock": clock, "account_identity": identity}

    def run_governor(proposal):
        return govern(proposal, view, clock, thresholds=context.governor_thresholds,
                      mode=context.mode, config_version=context.config_version)

    # -- 5. candidates ------------------------------------------------------
    spot, _pairs, _spread = estimate_spot(accepted, snapshots["snapshots"])
    report = {}
    candidates = build_candidates(
        accepted=accepted, snapshots=snapshots["snapshots"],
        contracts_by_symbol={c["symbol"]: c for c in contracts["option_contracts"]},
        spot=spot, governor_thresholds=context.governor_thresholds,
        run_governor=run_governor, report=report,
    )
    result["candidates"] = len(candidates)
    result["exclusions"] = report
    if not candidates:
        result["skipped"] = "no_candidates"
        return result

    # -- 6. govern, record, and act on the first approval -------------------
    rejections = set()

    for proposal in candidates:
        verdict = run_governor(proposal)
        ident = entry_id(now, proposal, context.config_version)
        failed = failing_rules(verdict)
        rejections.update(failed)
        root = _write_root(context, ts=now, as_of=as_of, proposal=proposal,
                           verdict=verdict, snapshot=snapshot, ident=ident)
        result["roots"].append({"id": root["id"], "status": root["status"],
                                "approved": verdict["approved"], "failed": failed})

        if not verdict["approved"]:
            continue

        result["approved"] += 1
        if context.submit:
            _submit_and_follow(context, root, result, now=now)
        else:
            _close_unsent(context, root, result, now=now)
        # At most one order per cycle: the view the next candidate was governed
        # against is the view this order has just invalidated.
        break

    result["rejections"] = sorted(rejections)
    return result


def _order_id_of(entries, root_id):
    """The broker order id on a chain already recorded, if it reached one."""
    for entry in ledger_mod.fold_chain(entries, root_id)["entries"]:
        order = entry.get("order") or {}
        if order.get("order_id"):
            return order["order_id"]
    return None


def _write_root(context, *, ts, as_of, proposal, verdict, snapshot, ident):
    """The decision entry, written PRE-submission (5a), before any order exists."""
    context.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    entry = context.ledger.append_root(
        id=ident, ts=ts, as_of=as_of, mode=verdict["mode"],
        status="approved_pending" if verdict["approved"] else "governor_rejected",
        config_version=context.config_version,
        prompt_version=None,          # hand-authored: no LLM produced this proposal
        code_version=context.code_version,
        approved_by=None, approved_at=None,   # nobody has confirmed yet (5a)
        snapshot=snapshot, proposal=proposal, verdict=verdict,
    )
    return context.record(entry)


def _close_unsent(context, root, result, *, now):
    """A rehearsal approved an order and did not send it. Say so on the chain.

    Without this, `--no-submit` leaves an `approved_pending` root: in flight
    forever, for an order that was never placed and is not coming. That is not
    untidiness — as of the churn fix, a chain in the risk-bearing set holds its
    underlying open and counts against the book's open risk, so the very next
    cycle of the same rehearsal would be refused by a position that does not
    exist, and every number after it would be about a phantom.

    Appended, never edited: the root stays exactly as written, carrying the real
    verdict the governor really reached, and a follow-up records that nothing
    was sent. `order` and `fill` are null because no order ever existed.
    """
    context.record(context.ledger.append_follow_up(
        id=f"{root['id']}+01-canceled", root_id=root["id"], ts=now,
        status="canceled", order=None, fill=None,
    ))
    result["order_status"] = "canceled_not_sent"
    return result


def _submit_and_follow(context, root, result, *, now):
    """Hand the approved root to the executor and follow it to a terminal state.

    The only function in this file that causes a position to exist. It adds no
    judgement of its own: the proposal was screened from live data, the governor
    approved it on its own arithmetic, and the root entry is already on disk
    carrying the id the order's `client_order_id` embeds.
    """
    executor = Executor(
        ledger=context.ledger, transport=context.transport, config=context.config,
        env=os.environ, expected_account_number=context.profile["account_number"],
    )
    payload = executor.build_order_request(root)
    submitted = executor.submit(root, ts=now)
    context.record(submitted["entry"])

    order = submitted["order"]
    result["order_id"] = order["order_id"]
    result["order_status"] = "submitted"
    result["submitted"] = 1
    result["resolved_existing"] = submitted["resolved_existing"]

    follow = context.runner["order_follow_seconds"]
    poll = context.runner["order_poll_seconds"]
    last = "submitted"
    for _ in range(max(1, int(follow // poll))):
        context.sleep(poll)
        broker = context.transport.get_order_by_client_id(payload["client_order_id"])
        if broker is None:
            break
        status = BROKER_STATUS_MAP.get(broker.get("status"))
        if status is None:
            # The shape 5 vocabulary is closed. Stop following rather than
            # translating an unknown broker state into the nearest word we own;
            # the chain is left where it is and the next cycle sees it.
            break
        if status != last:
            context.record(executor.record_transition(
                root["id"], broker, ts=datetime.now(timezone.utc)))
            last = status
            result["order_status"] = status
        if ledger_mod.is_terminal(status):
            break
    return result


# ---------------------------------------------------------------------------
# The log line — one cycle, one line
# ---------------------------------------------------------------------------

def format_cycle_line(result):
    """What a human watching a terminal on Thursday actually reads.

    One line, `key=value` columns in the seam's own detail convention, carrying
    the cycle id, the `as_of` the decision was made at, how many candidates there
    were, how the governor ruled, and then either the order or the reasons.
    """
    parts = [f"cycle={result['cycle_id']}",
             f"as_of={result['as_of']}",
             f"open={str(bool(result['market_open'])).lower()}"]

    if result["skipped"] == "market_closed":
        return " ".join(parts + ["skipped=market_closed"])

    screened = result.get("screened") or {}
    parts.append(f"screened={screened.get('accepted', 0)}/{screened.get('rejected', 0)}")
    parts.append(f"candidates={result['candidates']}")

    if result["skipped"] in ("no_candidates", "empty_chain"):
        return " ".join(parts + [f"skipped={result['skipped']}"])

    parts.append(f"approved={result['approved']}/{result['candidates']}")
    for root in result["roots"]:
        parts.append(f"root={root['id']}")

    if result["skipped"] == "idempotent":
        parts.append("skipped=idempotent")
        if result["order_id"]:
            parts.append(f"existing_order={result['order_id']}")
        return " ".join(parts)

    if result["order_id"]:
        parts.append(f"order={result['order_id']}")
        parts.append(f"status={result['order_status']}")
    elif result["rejections"]:
        parts.append("rejected_on=" + ",".join(result["rejections"]))
    elif result["approved"]:
        parts.append("no_submit=approved_then_canceled_unsent")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Building a real context
# ---------------------------------------------------------------------------

def build_context(env_file, *, mode="autopilot", submit=True, session=None,
                  transport=None, sleep=time.sleep):
    """Load the profile named by `env_file` and wire up a real run.

    `env_file` is never defaulted here or by either entry point's argument
    parser. `scripts/dry_run.py` defaults to `.env` (dev) so that reaching the
    scored account is always something a human typed; an UNATTENDED loop cannot
    borrow that reasoning, because a default of any kind means a session that
    ran for hours against whichever account the default happened to name.
    """
    profile = load_profile(env_file)
    load_dotenv(REPO / profile["env_file"])
    config = load_config()                     # the paper guard fires here
    runner = json.loads(RUNNER_CONFIG.read_text(encoding="utf-8"))
    governor_thresholds = json.loads(
        profile["governor_thresholds"].read_text(encoding="utf-8"))

    keep = ("account_number",) if profile["scored"] else ()
    return RunContext(
        profile=profile,
        config=config,
        governor_thresholds=governor_thresholds,
        screener_thresholds=json.loads(SCREENER_THRESHOLDS.read_text(encoding="utf-8")),
        datafeed_tunables=json.loads(DATAFEED_CONFIG.read_text(encoding="utf-8")),
        runner=runner,
        config_version=content_hash(profile["governor_thresholds"]),
        code_version=code_version(),
        mode=mode,
        submit=submit,
        feed=DataFeed(config, session=session),
        transport=transport or AlpacaPyTransport(config),
        ledger=ledger_mod.Ledger(profile["ledger"]),
        mirror=DemoMirror(profile["demo_sample"],
                          (config["api_key"], config["secret_key"]), keep=keep),
        sleep=sleep,
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env", required=True, default=None, metavar="FILE",
        help="which env file to load, and therefore WHICH ACCOUNT this cycle is "
             "for. REQUIRED and never defaulted: config/profiles.json maps it to "
             "an account number, a ledger, a demo sample and a governor config.",
    )
    parser.add_argument(
        "--no-submit", dest="submit", action="store_false",
        help="decide and record, but do not send anything to the broker. The "
             "governor still rules and the ledger still gets the root.",
    )
    parser.add_argument(
        "--mode", default="autopilot", choices=("autopilot", "approve"),
        help="ledger mode recorded on the decision. Autopilot is the honest "
             "value for an order the governor alone gated.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    context = build_context(args.env, mode=args.mode, submit=args.submit)
    print(f"profile={context.profile['name']} account={context.profile['account_number']} "
          f"scored={'YES' if context.profile['scored'] else 'no'} "
          f"submit={'YES' if context.submit else 'no'}")
    result = run_cycle(context, cycle_id="0001", now=datetime.now(timezone.utc))
    print(format_cycle_line(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
