"""GB-R — session runner contract suite.

The runner is the only component in GlassBox with a loop in it, and the only one
that decides to act more than once. Everything it drives is already under
contract — the screener screens, the governor governs, the executor executes,
the ledger records — so this suite is deliberately **not** about any of that.

It is about what an UNATTENDED process does:

  * when it declines to act (a closed market, a PAUSE file, a governed refusal);
  * when it stops (a stop time, two consecutive raised cycles, a broker that
    claims to be a different account);
  * what it writes down, so a session that traded nothing is still legible;
  * and whether running the same cycle twice opens two positions.

That last one is the property with money attached. Everything else in this
system is a decision made once and recorded; a loop is the first thing here that
can make the same decision twice, and `client_order_id` embedding the ledger
ROOT id is the reason the broker refuses the second one (shape 4). The runner
must not rely on that alone, and this suite holds it to both halves.

Two bands, as in every other suite here:

  GB-R-F**  fixture integrity — runs today, guards the hand-built chain and the
            runner config.
  GB-R-**   runner behaviour — strict-xfail until scripts/run_cycle.py and
            scripts/run_session.py land, then arms itself automatically.

**No network, in either band.** `FakeVenue` serves the chain and `FakeBroker`
records every submission; a test that reaches a venue is a test that cannot be
run on Thursday morning, which is the only morning that matters.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import (
    CONFIG_DIR,
    FAKE_CONFIG,
    BlindBroker,
    FakeBroker,
    FakeVenue,
    occ_symbol,
    requires_runner,
    requires_session,
)

#: The account the fake venue claims to be. Neither real account number appears
#: in this suite: a test that named the scored account could only ever be one
#: copy-paste away from pointing something real at it.
TEST_ACCOUNT = "PA0000RUNNERTEST"

#: The one thing the hand-built chain is supposed to yield, stated here so a
#: test reads as an assertion rather than as arithmetic.
SHORT_LEG = "SPY260903P00640000"
LONG_LEG = "SPY260903P00635000"
NET_CREDIT = -0.55
MAX_LOSS_PER_LOT = 445.00       # (5.00 width - 0.55 credit) * 100
APPROVED_QTY = 4                # 4 * 445.00 = 1,780.00, under a 2,000.00 cap
CENT = 0.005

OPEN_AT = datetime(2026, 9, 2, 15, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Building a context out of fakes
# ---------------------------------------------------------------------------

def _profile(tmp_path, *, account=TEST_ACCOUNT):
    """A run profile shaped exactly like one in config/profiles.json.

    Built here rather than read from that file: GB-R must be able to say what a
    profile means without the suite's answers depending on a config that names
    two real accounts.
    """
    return {
        "name": "gb-r", "scored": False, "env_file": ".env.gb-r",
        "account_number": account,
        "ledger": tmp_path / "ledger.jsonl",
        "demo_sample": tmp_path / "demo.jsonl",
        "governor_thresholds": CONFIG_DIR / "thresholds.competition.json",
    }


def make_context(tmp_path, venue, broker, *, mode="autopilot", submit=True,
                 account=TEST_ACCOUNT, mirror=None):
    """A `RunContext` over fakes — the same one `build_context` builds for real.

    The runner takes its collaborators by injection for the same reason every
    other module here does: a component that reaches out and builds its own
    transport can only be tested against the thing it reaches.
    """
    import run_cycle as R

    from glassbox import ledger as ledger_mod
    from glassbox.datafeed import DataFeed

    profile = _profile(tmp_path, account=account)
    return R.RunContext(
        profile=profile,
        config=FAKE_CONFIG,
        governor_thresholds=json.loads(
            (CONFIG_DIR / "thresholds.competition.json").read_text()),
        screener_thresholds=json.loads(
            (CONFIG_DIR.parent / "tests" / "fixtures" /
             "thresholds.PROPOSED.json").read_text()),
        datafeed_tunables=json.loads(
            (CONFIG_DIR / "datafeed.PROPOSED.json").read_text()),
        runner=json.loads((CONFIG_DIR / "runner.PROPOSED.json").read_text()),
        config_version="sha256:gb-r-not-a-real-config-hash",
        code_version="gb-r",
        mode=mode,
        submit=submit,
        feed=DataFeed(FAKE_CONFIG, session=venue),
        transport=broker,
        ledger=ledger_mod.Ledger(profile["ledger"]),
        mirror=mirror,
        sleep=lambda seconds: None,
    )


def account_body(number=TEST_ACCOUNT, equity=100000.0):
    return {"id": "b0000000-0000-4000-8000-00000000cafe",
            "account_number": number, "status": "ACTIVE",
            "cash": f"{equity:.2f}", "equity": f"{equity:.2f}",
            "buying_power": "400000.00"}


def seed_position(context, *, ts, qty, underlying="SPY", status="filled"):
    """Put a risk-bearing chain on the ledger, as an earlier cycle would have.

    The proposal is the same vertical the chain yields, so its computed max loss
    is `qty * 445.00` under the governor's OWN arithmetic — which is what the
    portfolio cap sums. Nothing here states a max loss; stating one would be
    handing the check the answer.
    """
    from glassbox import ledger as ledger_mod

    proposal = {
        "underlying": underlying, "structure": "vertical_spread", "qty": qty,
        "legs": [
            {"symbol": SHORT_LEG, "action": "sell", "option_type": "put",
             "strike": 640.0, "expiry": "2026-09-03", "ratio_qty": 1,
             "limit_price": 0.90},
            {"symbol": LONG_LEG, "action": "buy", "option_type": "put",
             "strike": 635.0, "expiry": "2026-09-03", "ratio_qty": 1,
             "limit_price": 0.35},
        ],
        "net_debit_credit": NET_CREDIT,
        "rationale": "GB-R seed: a position an earlier cycle opened",
        "claimed_max_loss": MAX_LOSS_PER_LOT * qty,
        "claimed_max_gain": 55.0 * qty,
    }
    root_id = f"seed-{underlying}-{ts.strftime('%H%M%S')}-{qty}"
    root = context.ledger.append_root(
        id=root_id, ts=ts, as_of=ledger_mod.iso_utc(ts), mode="autopilot",
        status="approved_pending", config_version=context.config_version,
        prompt_version=None, code_version=context.code_version,
        approved_by=None, approved_at=None,
        snapshot={"account_state": {}, "clock": {}},
        proposal=proposal,
        verdict={"approved": True, "checks": [], "mode": "autopilot",
                 "config_version": context.config_version, "reason": "seeded"},
    )
    if status != "approved_pending":
        context.ledger.append_follow_up(
            id=f"{root_id}+01-{status}", root_id=root_id, ts=ts,
            status=status, order=None, fill=None,
        )
    return root


def venue_for(chain, *, as_of=OPEN_AT, is_open=True, equity=100000.0):
    account = dict(chain["account"], equity=equity, cash=equity)
    return FakeVenue(chain, as_of=as_of, is_open=is_open, account=account)


def broker_for(responses, *, number=TEST_ACCOUNT, equity=100000.0,
               statuses=("accepted", "filled")):
    return FakeBroker(responses, account_body(number, equity), statuses=statuses)


def failing_rules(root_entry):
    return sorted(c["rule"] for c in root_entry["verdict"]["checks"]
                  if not c["passed"])


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_r_f01_the_runner_config_is_proposed_and_complete(runner_config):
    """GB-R-F01: the loop's tunables are in config, PROPOSED, and all present.

    None of these is a risk limit — the governor holds every one of those — but
    a number that governs an unattended process still belongs in a file with a
    diff on it rather than inside a script.
    """
    assert "PROPOSED" in runner_config["_status"]
    for key in ("cycle_interval_seconds", "max_consecutive_errors", "pause_file",
                "order_follow_seconds", "order_poll_seconds"):
        assert key in runner_config, f"missing tunable {key}"

    # Every decision in the file carries its reasoning next to it. A number with
    # no argument attached is a number nobody can disagree with later.
    for rationale in ("_cycle_interval_rationale", "_max_consecutive_errors_rationale",
                      "_pause_file_rationale", "_order_follow_rationale"):
        assert len(runner_config.get(rationale, "")) > 80, rationale

    assert runner_config["cycle_interval_seconds"] == 900, "the PROPOSED interval"
    assert runner_config["max_consecutive_errors"] >= 2, (
        "one raised cycle is a transient; the tolerance must allow for one"
    )
    assert runner_config["order_follow_seconds"] > runner_config["order_poll_seconds"]

    governor = json.loads((CONFIG_DIR / "thresholds.competition.json").read_text())
    assert runner_config["cycle_interval_seconds"] < governor["churn_window_seconds"], (
        "the interval must sit INSIDE the churn window. The loop is not what "
        "stops a position stacking on an underlying — the governor is — and an "
        "interval longer than the window would hide that by making it never come up"
    )


def test_gb_r_f02_the_chain_yields_exactly_one_governable_vertical(
    runner_chain, tmp_path
):
    """GB-R-F02: the fake chain's answer, derived here without the runner.

    Every assertion the behaviour band makes about an approved order rests on
    this one pair being the only pair. It is checked independently so that a
    runner bug and a fixture drift cannot be mistaken for one another.
    """
    from glassbox.datafeed import DataFeed
    from glassbox.governor import compose_account_view, computed_max_loss, govern
    from glassbox.screener import screen_chain

    import dry_run as harness

    thresholds = json.loads((CONFIG_DIR / "thresholds.competition.json").read_text())
    screener_thresholds = json.loads(
        (CONFIG_DIR.parent / "tests" / "fixtures" / "thresholds.PROPOSED.json").read_text())

    venue = venue_for(runner_chain)
    feed = DataFeed(FAKE_CONFIG, session=venue)
    contracts = feed.fetch_contracts("SPY", expiration_date_gte="2026-09-02",
                                     expiration_date_lte="2026-09-03", as_of=OPEN_AT)
    symbols = [c["symbol"] for c in contracts["option_contracts"]]
    snapshots = feed.fetch_snapshots(symbols, as_of=OPEN_AT)

    screened = screen_chain(contracts, snapshots, as_of=OPEN_AT,
                            thresholds=screener_thresholds)
    assert not screened["rejected"], (
        "the chain is fully quoted with complete greeks: the screener's fail-closed "
        "behaviour is GB-S's subject, and a chain that lost contracts here would "
        "make every GB-R count mean something else"
    )

    accepted, snaps = screened["accepted"], snapshots["snapshots"]
    spot, _pairs, _spread = harness.estimate_spot(accepted, snaps)
    report = {}
    proposal = harness.build_pass_vertical(
        accepted, snaps, {c["symbol"]: c for c in contracts["option_contracts"]},
        spot, width=5.0, window=thresholds["liquidity_window"], qty=1, report=report,
    )

    # Exactly one pair survives, and every other one is excluded by a DIFFERENT
    # test, so a change that breaks one of them is legible in this counter.
    assert report["candidates"] == 1
    assert report["short_delta_band"] == 2
    assert report["short_open_interest"] == 1
    assert report["long_open_interest"] == 1

    assert [leg["symbol"] for leg in proposal["legs"]] == [SHORT_LEG, LONG_LEG]
    assert proposal["net_debit_credit"] == pytest.approx(NET_CREDIT, abs=CENT)
    assert computed_max_loss(proposal) == pytest.approx(MAX_LOSS_PER_LOT, abs=CENT)

    # And the size the governor will approve, found by asking it — the same way
    # the runner must, and never by computing the cap a second time.
    raw = feed.fetch_raw_account_state(as_of=OPEN_AT)
    view = compose_account_view(raw, [], 100000.0)
    clock = feed.fetch_clock()

    def run_governor(candidate):
        return govern(candidate, view, clock, thresholds=thresholds,
                      mode="autopilot", config_version="sha256:gb-r")

    sized, verdict, _attempts = harness.size_by_asking_the_governor(
        lambda qty: harness.build_pass_vertical(
            accepted, snaps, {c["symbol"]: c for c in contracts["option_contracts"]},
            spot, width=5.0, window=thresholds["liquidity_window"], qty=qty),
        run_governor,
    )
    assert verdict["approved"] is True
    assert sized["qty"] == APPROVED_QTY
    assert computed_max_loss(sized) == pytest.approx(
        MAX_LOSS_PER_LOT * APPROVED_QTY, abs=CENT)


# ---------------------------------------------------------------------------
# One cycle
# ---------------------------------------------------------------------------

@requires_runner
def test_gb_r_01_a_cycle_screens_governs_submits_and_records(runner_chain, tmp_path,
                                                             broker_responses):
    """GB-R-01: the whole cycle, end to end, against a venue that never existed.

    One pass: identity, clock, chain, screen, propose, compose, govern, submit,
    follow, ledger. The assertions are on the SEAMS between those steps — that
    each one's output is what the next one was handed — because each step's own
    behaviour has a suite of its own.
    """
    import run_cycle as R

    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)

    result = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)

    assert result["skipped"] is None
    assert result["market_open"] is True
    assert result["as_of"] == "2026-09-02T15:30:00Z"
    assert result["candidates"] == 1
    assert result["approved"] == 1
    assert result["rejections"] == []

    # The order that went out is the one the governor approved, at the size it
    # approved, and nothing else was sent.
    assert len(broker.submitted) == 1
    payload = broker.submitted[0]
    assert payload["qty"] == APPROVED_QTY
    assert [leg["symbol"] for leg in payload["legs"]] == [SHORT_LEG, LONG_LEG]
    assert result["order_id"] == broker.orders[payload["client_order_id"]]["id"]
    assert result["order_status"] == "filled"

    # The chain on the ledger: root written PRE-submission (5a), then the
    # transitions, folded by root_id.
    from glassbox import ledger as ledger_mod

    entries = context.ledger.read_entries()
    roots = ledger_mod.list_roots(entries)
    assert len(roots) == 1
    root = roots[0]
    assert root["status"] == "approved_pending"
    assert root["mode"] == "autopilot"
    assert root["verdict"]["approved"] is True
    assert payload["client_order_id"].endswith(root["id"]), (
        "the client_order_id embeds the ROOT entry id (shape 4) — that is what "
        "makes a retry a duplicate the broker refuses rather than a second position"
    )
    status, terminal = ledger_mod.current_status(entries, root["id"])
    assert (status, terminal) == ("filled", True)
    assert [e["status"] for e in ledger_mod.fold_chain(entries, root["id"])["entries"]] \
        == ["approved_pending", "submitted", "filled"]

    # And the identity guard ran on this cycle, before any of it.
    assert broker.account_reads >= 1


@requires_runner
def test_gb_r_02_a_closed_market_submits_nothing_and_writes_nothing(runner_chain,
                                                                    tmp_path,
                                                                    broker_responses):
    """GB-R-02: the market is closed. Nothing is sent, and nothing is recorded.

    "It raised" would be a weaker claim than this. The assertions are that the
    broker received NOTHING and the ledger is empty — the GB-E-23 standard — and
    additionally that the cycle never even asked for the chain, because a loop
    that fetches, screens and governs its way to a foregone refusal every
    quarter of an hour fills a scored account's ledger with noise.

    The governor's `market_open` check remains the gate on any order (6c); this
    is the loop declining to spend a cycle, and it fails closed.
    """
    import run_cycle as R

    venue = venue_for(runner_chain, is_open=False)
    broker = broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)

    result = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)

    assert result["skipped"] == "market_closed"
    assert result["market_open"] is False
    assert result["candidates"] == 0
    assert result["order_id"] is None

    assert broker.submitted == [], "no order may leave a closed-market cycle"
    assert context.ledger.read_entries() == []
    assert not any("/options/contracts" in request["path"]
                   for request in venue.requests), (
        "a foregone refusal is not worth a chain fetch, let alone a ledger root"
    )
    # It still resolved an as_of off the venue's own clock and calendar, so the
    # log line says WHEN it declined rather than only that it did.
    assert result["as_of"], "a skipped cycle still reports the as_of it skipped at"


@requires_runner
def test_gb_r_03_re_running_a_cycle_never_opens_a_second_position(runner_chain,
                                                                  tmp_path,
                                                                  broker_responses):
    """GB-R-03: idempotency. The same root id must never be submitted twice.

    A loop is the first component here that can make the same decision twice.
    Two independent things must hold, and this asserts both:

      1. the runner recognises a root id already on its ledger and does not
         re-decide, re-append or re-submit it;
      2. `client_order_id` embeds that root id, so even if it did, the broker
         would refuse the duplicate rather than opening a second position.
    """
    import run_cycle as R

    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)

    first = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)
    entries_after_first = context.ledger.read_entries()
    assert first["approved"] == 1 and len(broker.submitted) == 1

    # The identical cycle, re-run: same clock, same chain, same proposal, and
    # therefore the same content-hashed root id.
    second = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)

    assert second["skipped"] == "idempotent"
    assert len(broker.submitted) == 1, "a re-run cycle must not reach the wire"
    assert context.ledger.read_entries() == entries_after_first, (
        "the ledger is byte-identical: a re-run appends nothing at all"
    )
    assert second["order_id"] == first["order_id"], (
        "the re-run resolves to the order that already exists, and says so"
    )


@requires_runner
def test_gb_r_04_a_cycle_with_nothing_approvable_still_records_why(runner_chain,
                                                                   tmp_path,
                                                                   broker_responses):
    """GB-R-04: a governed refusal is an outcome, and it is written down.

    The failure this guards against is a loop that quietly does nothing for six
    hours. A session that traded once and refused twenty times must be able to
    say what the twenty refusals were, from the ledger alone, months later — so
    the rejected root carries the whole `checks[]`, not a summary.
    """
    import run_cycle as R

    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)
    # A position opened four minutes ago: inside both the churn window and the
    # minimum hold, so this underlying is not available.
    seed_position(context, ts=OPEN_AT - timedelta(minutes=4), qty=1)

    result = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)

    assert result["skipped"] is None, "it ran; it simply had nothing approvable"
    assert result["candidates"] == 1
    assert result["approved"] == 0
    assert result["rejections"] == ["churn_guard"]
    assert result["order_id"] is None
    assert broker.submitted == []

    from glassbox import ledger as ledger_mod

    entries = context.ledger.read_entries()
    written = [r for r in ledger_mod.list_roots(entries)
               if not r["id"].startswith("seed-")]
    assert len(written) == 1
    root = written[0]
    assert root["status"] == "governor_rejected"
    assert ledger_mod.current_status(entries, root["id"]) == ("governor_rejected", True)
    assert failing_rules(root) == ["churn_guard"]
    # The whole verdict, not a summary of it: every check, passed ones included,
    # with the numbers the decision turned on.
    assert len(root["verdict"]["checks"]) == 10
    assert all(check["detail"] for check in root["verdict"]["checks"])
    assert root["snapshot"]["account_state"]["ledger"]["recent_activity"]["SPY"]
    assert root["order"] is None and root["fill"] is None


@requires_runner
def test_gb_r_05_churn_blocks_stacking_on_consecutive_cycles(runner_chain, tmp_path,
                                                             broker_responses):
    """GB-R-05: two cycles, one position. The second is refused on `churn_guard`.

    THE test this runner exists to pass. On 2026-09-02 two orders went onto the
    same underlying 55 seconds apart because the composed account view answered
    "when did we last open?" over the chains still in flight, and the first had
    already filled. A loop turns that from an accident into a policy: fifteen
    minutes apart, all afternoon, until the caps bite.

    So this drives the real cycle twice, one interval apart, over a broker that
    FILLS — and the second cycle must be refused by the same guard that was
    blind to a fill this morning.
    """
    import run_cycle as R

    interval = timedelta(seconds=900)
    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)

    first = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)
    assert first["approved"] == 1 and first["order_status"] == "filled"

    # The next cycle, fifteen minutes later. The venue's clock moves with it.
    venue.as_of = OPEN_AT + interval
    second = R.run_cycle(context, cycle_id="0002", now=venue.as_of)

    assert second["approved"] == 0
    assert second["rejections"] == ["churn_guard"]
    assert len(broker.submitted) == 1, "the second cycle must not reach the wire"

    from glassbox import ledger as ledger_mod

    entries = context.ledger.read_entries()
    rejected = [r for r in ledger_mod.list_roots(entries)
                if r["status"] == "governor_rejected"]
    assert len(rejected) == 1
    detail = [c["detail"] for c in rejected[0]["verdict"]["checks"]
              if c["rule"] == "churn_guard"][0]
    assert "seconds_since_last_open=900" in detail, (
        "the guard must be able to say how long ago — a FILLED chain is what it "
        "is reading, and the whole defect was that it read `null`"
    )
    assert "re-entry on this underlying inside the churn window" in detail


@requires_runner
def test_gb_r_06_the_per_underlying_cap_holds_across_cycles(runner_chain, tmp_path,
                                                            broker_responses):
    """GB-R-06: two positions already on SPY, and the cap is two.

    Churn is a cooldown and expires; the position cap does not. A loop that ran
    long enough for every cooldown to lapse would still be bounded, and this is
    the check that bounds it.
    """
    import run_cycle as R

    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)
    # Yesterday: far outside the churn window AND the minimum hold, so the only
    # thing that can refuse this cycle is the cap itself.
    yesterday = OPEN_AT - timedelta(days=1)
    seed_position(context, ts=yesterday, qty=1)
    seed_position(context, ts=yesterday + timedelta(minutes=1), qty=1)

    result = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)

    assert result["approved"] == 0
    assert result["rejections"] == ["x_position_cap"], (
        "the cooldowns have lapsed; the cap is the only thing left refusing"
    )
    assert broker.submitted == []

    from glassbox import ledger as ledger_mod

    entries = context.ledger.read_entries()
    root = [r for r in ledger_mod.list_roots(entries)
            if r["status"] == "governor_rejected"][0]
    detail = [c["detail"] for c in root["verdict"]["checks"]
              if c["rule"] == "x_position_cap"][0]
    assert "open_for_underlying=2" in detail and "max_open_per_underlying=2" in detail


@requires_runner
def test_gb_r_07_total_open_risk_bounds_the_book_across_cycles(runner_chain, tmp_path,
                                                               broker_responses):
    """GB-R-07: the portfolio cap, which is the one that bounds a LOOP.

    Per-trade caps bound one trade. A loop's whole failure mode is many trades
    that are each individually fine, so this is the check with the runner's name
    on it — and it must bind in both of its forms:

      (a) it forces the SIZE down, so the book stops exactly at the cap rather
          than at whatever the last approvable lot happened to be; and
      (b) when even one lot will not fit, nothing is approvable at all.
    """
    import run_cycle as R

    from glassbox.governor import computed_max_loss

    cap = 10000.00      # 10% of 100,000.00 equity, config/thresholds.competition.json
    yesterday = OPEN_AT - timedelta(days=1)

    # (a) 21 lots already open = 9,345.00. One more lot fits; four do not.
    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path / "a", venue, broker)
    context.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    seed_position(context, ts=yesterday, qty=21)

    result = R.run_cycle(context, cycle_id="0001", now=OPEN_AT)
    assert result["approved"] == 1
    assert len(broker.submitted) == 1
    assert broker.submitted[0]["qty"] == 1, (
        "the cap forced the size down; the runner never computed it, it asked"
    )

    from glassbox import ledger as ledger_mod

    entries = context.ledger.read_entries()
    on_the_book = sum(
        computed_max_loss(root["proposal"]) or 0.0
        for root in ledger_mod.list_roots(entries)
        if ledger_mod.current_status(entries, root["id"])[0] in
        {"approved_pending", "submitted", "partial_fill", "filled"}
    )
    assert on_the_book <= cap + CENT, (
        f"the book stands at {on_the_book:.2f} against a {cap:.2f} cap"
    )

    # (b) 22 lots already open = 9,790.00. Even one more lot breaches the cap.
    venue_b, broker_b = venue_for(runner_chain), broker_for(broker_responses)
    context_b = make_context(tmp_path / "b", venue_b, broker_b)
    context_b.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    seed_position(context_b, ts=yesterday, qty=22)

    result_b = R.run_cycle(context_b, cycle_id="0001", now=OPEN_AT)
    assert result_b["approved"] == 0
    assert result_b["rejections"] == ["x_total_open_risk"]
    assert broker_b.submitted == []

    root = [r for r in ledger_mod.list_roots(context_b.ledger.read_entries())
            if r["status"] == "governor_rejected"][0]
    detail = [c["detail"] for c in root["verdict"]["checks"]
              if c["rule"] == "x_total_open_risk"][0]
    assert "open_risk_before=9790.00" in detail
    assert "cap=10000.00" in detail and "cap_basis=0.1_of_equity" in detail


@requires_runner
def test_gb_r_08_the_identity_guard_runs_on_every_cycle(runner_chain, tmp_path,
                                                        broker_responses):
    """GB-R-08: every cycle asks the broker who it is, and stops if it is wrong.

    Once per session is not enough. A session runs for six hours unattended; the
    guard is cheap; and the failure it prevents — an order on the wrong one of
    two indistinguishable paper accounts — cannot be taken back.

    A wrong answer and NO answer are both hard stops. "I could not check" must
    never resolve to "it is fine".
    """
    import run_cycle as R

    from glassbox.executor import AccountIdentityError

    wrong = broker_for(broker_responses, number="PA9999NOTOURS")
    context = make_context(tmp_path / "wrong", venue_for(runner_chain), wrong)
    context.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(AccountIdentityError):
        R.run_cycle(context, cycle_id="0001", now=OPEN_AT)
    assert wrong.submitted == []
    assert context.ledger.read_entries() == []

    blind = BlindBroker(broker_responses, account_body())
    context_b = make_context(tmp_path / "blind", venue_for(runner_chain), blind)
    context_b.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(Exception):
        R.run_cycle(context_b, cycle_id="0001", now=OPEN_AT)
    assert blind.submitted == []
    assert context_b.ledger.read_entries() == []

    # And it is the FIRST thing the cycle does: nothing was fetched, screened or
    # proposed before the account was confirmed.
    venue = venue_for(runner_chain)
    context_c = make_context(tmp_path / "order", venue,
                             broker_for(broker_responses, number="PA9999NOTOURS"))
    context_c.profile["ledger"].parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(AccountIdentityError):
        R.run_cycle(context_c, cycle_id="0001", now=OPEN_AT)
    assert venue.requests == [], "the identity guard runs before anything costs time"


@requires_runner
def test_gb_r_09_the_log_line_says_what_the_cycle_did(runner_chain, tmp_path,
                                                      broker_responses):
    """GB-R-09: one line per cycle, and it answers the questions you would ask.

    The log is the only thing a human watches on Thursday. It must carry the
    cycle id, the `as_of` the decision was made at, how many candidates there
    were, how the governor ruled, and then either the order id or the reasons —
    on one line, because a human scanning a terminal reads columns, not prose.
    """
    import run_cycle as R

    venue, broker = venue_for(runner_chain), broker_for(broker_responses)
    context = make_context(tmp_path, venue, broker)

    approved = R.format_cycle_line(R.run_cycle(context, cycle_id="0001", now=OPEN_AT))
    assert "cycle=0001" in approved
    assert "as_of=2026-09-02T15:30:00Z" in approved
    assert "candidates=1" in approved
    assert "approved=1/1" in approved
    assert "order=" in approved and "status=filled" in approved
    assert "\n" not in approved, "one cycle, one line"

    venue.as_of = OPEN_AT + timedelta(seconds=900)
    refused = R.format_cycle_line(
        R.run_cycle(context, cycle_id="0002", now=venue.as_of))
    assert "cycle=0002" in refused
    assert "approved=0/1" in refused
    assert "rejected_on=churn_guard" in refused
    assert "order=" not in refused, "there is no order to name, so none is named"
    assert "\n" not in refused

    closed_venue = venue_for(runner_chain, is_open=False)
    closed = R.format_cycle_line(R.run_cycle(
        make_context(tmp_path / "closed", closed_venue, broker_for(broker_responses)),
        cycle_id="0003", now=OPEN_AT))
    assert "cycle=0003" in closed and "skipped=market_closed" in closed


# ---------------------------------------------------------------------------
# The session loop
# ---------------------------------------------------------------------------

class Ticker:
    """A clock the test owns, advanced only by the loop's own sleeps."""

    def __init__(self, start):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def counting_cycle(results=None, raises=()):
    """A stand-in cycle. GB-R's session tests are about the LOOP, not the cycle."""
    calls = []

    def cycle(context, *, cycle_id, now):
        calls.append((cycle_id, now))
        index = len(calls) - 1
        if index < len(raises) and raises[index]:
            raise raises[index]
        return {"cycle_id": cycle_id, "as_of": now.isoformat(), "market_open": True,
                "candidates": 0, "approved": 0, "rejections": [], "roots": [],
                "order_id": None, "order_status": None, "skipped": "stub",
                "submitted": 0}

    cycle.calls = calls
    return cycle


@requires_session
def test_gb_r_10_the_session_stops_at_its_stop_time(tmp_path):
    """GB-R-10: a session ends when it says it will, not when it runs out of work.

    The stop time is a hard boundary and not a suggestion: on Thursday it is
    fifteen minutes before the close, so that anything the last cycle submits
    has time to fill inside the scored window.
    """
    import run_session as S

    ticker = Ticker(OPEN_AT)
    cycle = counting_cycle()
    code = S.run_session(
        context=None, stop_at=OPEN_AT + timedelta(seconds=2700),
        interval_seconds=900, pause_file=tmp_path / "PAUSE",
        max_consecutive_errors=2, now=ticker, sleep=ticker.sleep,
        log=lambda line: None, cycle=cycle,
    )
    assert code == 0
    # 15:30, 15:45, 16:00 — and 16:15 is the stop, so it is not run.
    assert [cycle_id for cycle_id, _ in cycle.calls] == ["0001", "0002", "0003"]
    assert ticker.now >= OPEN_AT + timedelta(seconds=2700)


@requires_session
def test_gb_r_11_a_pause_file_suspends_the_loop_without_ending_it(tmp_path):
    """GB-R-11: `touch PAUSE` suspends cycles; `rm PAUSE` resumes them.

    A file, because a file needs no signal, no pid, no terminal and no second
    process: it works from any shell, and from a phone over ssh. A paused
    session keeps ticking and keeps LOGGING, so silence never means "paused" —
    silence means something is wrong.
    """
    import run_session as S

    pause = tmp_path / "PAUSE"
    pause.write_text("held by teakeycee\n")

    ticker = Ticker(OPEN_AT)
    cycle = counting_cycle()
    lines = []

    def sleep(seconds):
        ticker.sleep(seconds)
        if len(ticker.slept) == 2:      # two ticks paused, then release it
            pause.unlink()

    code = S.run_session(
        context=None, stop_at=OPEN_AT + timedelta(seconds=2700),
        interval_seconds=900, pause_file=pause, max_consecutive_errors=2,
        now=ticker, sleep=sleep, log=lines.append, cycle=cycle,
    )

    assert code == 0
    assert len(cycle.calls) == 1, (
        "two ticks were paused and the third ran; a paused tick must not consume "
        "a cycle, and must not be silent"
    )
    assert sum("pause" in line.lower() for line in lines) == 2
    assert any("PAUSE" in line for line in lines), (
        "the log must name the file, so whoever finds the session paused knows "
        "what to delete"
    )


@requires_session
def test_gb_r_12_two_consecutive_raised_cycles_halt_the_session(tmp_path):
    """GB-R-12: one raise is a transient; two in a row is a hard kill.

    An unattended loop that keeps retrying into a fault spends the afternoon
    doing nothing while looking busy, and on Thursday that is the whole session.
    The count is of CONSECUTIVE failures — a successful cycle resets it — so a
    venue that hiccups once an hour never stops the run.
    """
    import run_session as S

    boom = RuntimeError("the venue returned a 502")

    ticker = Ticker(OPEN_AT)
    cycle = counting_cycle(raises=[boom, boom, boom])
    lines = []
    code = S.run_session(
        context=None, stop_at=OPEN_AT + timedelta(hours=6), interval_seconds=900,
        pause_file=tmp_path / "PAUSE", max_consecutive_errors=2,
        now=ticker, sleep=ticker.sleep, log=lines.append, cycle=cycle,
    )
    assert code != 0, "a halted session must not exit 0"
    assert len(cycle.calls) == 2, "it stopped ON the second failure, not after a third"
    assert any("HALT" in line for line in lines)
    assert any("502" in line for line in lines), (
        "the log must carry what actually failed, not only that something did"
    )

    # A failure between successes is a transient and never halts the run.
    ticker = Ticker(OPEN_AT)
    cycle = counting_cycle(raises=[boom, None, boom, None])
    code = S.run_session(
        context=None, stop_at=OPEN_AT + timedelta(seconds=3600), interval_seconds=900,
        pause_file=tmp_path / "PAUSE", max_consecutive_errors=2,
        now=ticker, sleep=ticker.sleep, log=lambda line: None, cycle=cycle,
    )
    assert code == 0
    assert len(cycle.calls) == 4


@requires_session
def test_gb_r_13_an_identity_failure_halts_at_once(tmp_path):
    """GB-R-13: the wrong account does not get a second chance.

    Every other failure is worth one retry, because most of them are the venue
    having a bad second. A broker that says it is a different account is not a
    transient, and the one thing an unattended loop must never do with it is try
    again in fifteen minutes.
    """
    import run_session as S

    from glassbox.executor import AccountIdentityError

    ticker = Ticker(OPEN_AT)
    cycle = counting_cycle(raises=[AccountIdentityError("expected A, got B")])
    lines = []
    code = S.run_session(
        context=None, stop_at=OPEN_AT + timedelta(hours=6), interval_seconds=900,
        pause_file=tmp_path / "PAUSE", max_consecutive_errors=2,
        now=ticker, sleep=ticker.sleep, log=lines.append, cycle=cycle,
    )
    assert code != 0
    assert len(cycle.calls) == 1, "it halted on the first one, with no retry"
    assert any("HALT" in line for line in lines)


@requires_session
def test_gb_r_14_the_account_is_chosen_by_an_explicit_env_and_never_defaulted():
    """GB-R-14: `--env` has no default, in either entry point.

    `scripts/dry_run.py` defaults to `.env` (dev) because reaching the scored
    account must be something a human typed. An UNATTENDED loop cannot rely on
    that reasoning in reverse — a default of any kind means a session that ran
    six hours against whichever account the default happened to name. So there
    is no default at all, and a run with no `--env` does not start.
    """
    import run_cycle as R
    import run_session as S

    for module in (R, S):
        parser = module.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])
        action = next(a for a in parser._actions if "--env" in (a.option_strings or []))
        assert action.required is True, f"{module.__name__}: --env must be required"
        assert action.default is None, f"{module.__name__}: --env must have no default"

    # And the session loop requires a stop time for the same reason: a loop with
    # a defaulted end is a loop that ends when someone remembers it.
    stop = next(a for a in S.build_parser()._actions
                if "--stop" in (a.option_strings or []))
    assert stop.required is True
