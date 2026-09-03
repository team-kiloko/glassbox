"""GB-X — audit dashboard contract suite.

The dashboard (``app/dashboard.py``) is the consumer GB_INTERFACES.md shape 5
names: it folds chains by root id, renders ``checks[]`` generically, and puts
the paired approved / rejected roots side by side. Its pure functions are what
this suite holds to the record; the Streamlit page itself is not tested.

Every criterion runs against the two COMMITTED demo ledgers — real runs of the
real pipeline, not fixtures — so a change to either file, or to the ledger
helpers the dashboard leans on, shows up here.

  GB-X-01..04  folding: rows come from the ledger's own fold, never adjacency
  GB-X-05..08  checks: core, x_ and unknown rules render alike, nothing dropped
  GB-X-09..12  pairs: the hero pair, its numbers read from verdict.reason
  GB-X-13..16  replay: read-only, by content hash, refuses to guess
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import dashboard
from glassbox.ledger import current_status, fold_chain, list_roots, load

REPO = Path(__file__).resolve().parent.parent
COMPETITION = REPO / "demo" / "ledger_competition_sample.jsonl"
DEV = REPO / "demo" / "ledger_sample.jsonl"

#: The brief's two hero ids: the rejected proof root and its approved twin.
PROOF_REJECTED = "20260902T150903Z-f6d2bb6ef6"
PROOF_APPROVED = "20260902T150903Z-973c931c1d"


@pytest.fixture(scope="session")
def competition():
    return load(COMPETITION)


@pytest.fixture(scope="session")
def dev():
    return load(DEV)


@pytest.fixture(scope="session", params=[COMPETITION, DEV], ids=["competition", "dev"])
def entries(request):
    return load(request.param)


# ---------------------------------------------------------------------------
# GB-X-01..04 — folding
# ---------------------------------------------------------------------------

def test_gbx01_one_row_per_root_in_append_order(entries):
    """GB-X-01: the roots view has exactly the ledger's roots, in ledger order."""
    rows = dashboard.root_rows(entries)
    assert [r["id"] for r in rows] == [r["id"] for r in list_roots(entries)]
    assert len(rows) == len({r["id"] for r in rows})


def test_gbx02_row_status_is_the_folded_status(entries):
    """GB-X-02: a row's status is the chain's latest, never the root's own."""
    for row in dashboard.root_rows(entries):
        status, terminal = current_status(entries, row["id"])
        assert row["status"] == status
        assert row["terminal"] is terminal
    # The competition sample's filled chains prove the point: a root is written
    # as approved_pending and must NOT be shown that way.
    filled = [r for r in dashboard.root_rows(load(COMPETITION)) if r["status"] == "filled"]
    assert len(filled) == 2


def test_gbx03_timeline_is_the_ledger_fold_not_adjacency(competition):
    """GB-X-03: the two competition chains interleave with the rejected roots;
    a fold that walked forward by adjacency would swallow the neighbour."""
    timeline = dashboard.chain_timeline(competition, PROOF_APPROVED)
    chain = fold_chain(competition, PROOF_APPROVED)
    assert [s["id"] for s in timeline["steps"]] == [e["id"] for e in chain["entries"]]
    assert [s["status"] for s in timeline["steps"]] == ["approved_pending", "submitted", "filled"]
    assert PROOF_REJECTED not in {s["id"] for s in timeline["steps"]}
    assert timeline["steps"][0]["is_root"] and timeline["steps"][-1]["order_id"]
    assert timeline["terminal"] is True


def test_gbx04_partial_fill_is_not_terminal_and_rows_carry_provenance(entries):
    """GB-X-04: the dashboard takes terminality from the ledger, and every row
    carries the three versions and the claimed-vs-computed pair."""
    for row in dashboard.root_rows(entries):
        if row["status"] == "partial_fill":
            assert row["terminal"] is False
        for field in ("config_version", "code_version", "structure", "underlying", "qty"):
            assert row[field] is not None, (row["id"], field)
        assert "prompt_version" in row          # null is a statement, not a gap
        assert row["computed_max_loss"] is not None, row["id"]
        assert row["claimed_max_loss"] is not None, row["id"]
    assert dashboard.chain_timeline.__doc__      # documented, like the helpers


# ---------------------------------------------------------------------------
# GB-X-05..08 — checks render generically
# ---------------------------------------------------------------------------

def test_gbx05_every_check_renders_nothing_dropped(entries):
    """GB-X-05: rendered rows are 1:1 with verdict.checks, in order."""
    for root in list_roots(entries):
        rendered = dashboard.render_checks(root["verdict"])
        assert [r["rule"] for r in rendered] == [c["rule"] for c in root["verdict"]["checks"]]
        assert [r["passed"] for r in rendered] == [c["passed"] for c in root["verdict"]["checks"]]


def test_gbx06_core_and_x_rules_are_labelled_and_present(competition):
    """GB-X-06: the seven seam names are 'core', the governor's extensions are
    'x', and the competition verdicts carry both."""
    rendered = dashboard.render_checks(list_roots(competition)[0]["verdict"])
    kinds = {r["rule"]: r["kind"] for r in rendered}
    for rule in dashboard.CORE_RULES:
        assert kinds[rule] == "core", rule
    assert kinds["x_total_open_risk"] == "x"
    assert kinds["x_max_expiry"] == "x"
    assert kinds["x_position_cap"] == "x"


def test_gbx07_unknown_rule_still_renders():
    """GB-X-07: a rule name the dashboard has never seen renders with the same
    columns — dropping it would hide a decision."""
    verdict = {"approved": False, "mode": "autopilot", "config_version": "sha256:x",
               "reason": "rejected on y_future_rule",
               "checks": [
                   {"rule": "y_future_rule", "passed": False, "detail": "foo=1.50 vs bar=2.00"},
                   {"rule": None, "passed": True, "detail": None},
               ]}
    rendered = dashboard.render_checks(verdict)
    assert rendered[0] == {"rule": "y_future_rule", "passed": False, "kind": "unknown",
                           "detail": "foo=1.50 vs bar=2.00",
                           "numbers": {"foo": 1.5, "bar": 2.0}}
    assert rendered[1]["rule"] == "(unnamed)" and rendered[1]["detail"] == ""
    assert dashboard.render_checks({}) == [] and dashboard.render_checks(None) == []


def test_gbx08_parse_detail_reads_the_governors_numbers():
    """GB-X-08: key=value extraction — floats, null, booleans, first wins."""
    parsed = dashboard.parse_detail(
        "computed_max_loss=152584.00 vs cap=2000.00 cap_basis=0.02_of_equity "
        "seconds_since_last_open=null per_share=true computed_max_loss=1.00"
    )
    assert parsed["computed_max_loss"] == 152584.0
    assert parsed["cap"] == 2000.0
    assert parsed["cap_basis"] == "0.02_of_equity"
    assert parsed["seconds_since_last_open"] is None
    assert parsed["per_share"] is True
    assert dashboard.parse_detail(None) == {}


# ---------------------------------------------------------------------------
# GB-X-09..12 — the hero pair
# ---------------------------------------------------------------------------

def test_gbx09_competition_pairs_are_the_two_scored_runs(competition):
    """GB-X-09: both runs pair an approved root with its rejected twin, on the
    same config_version and the same as_of second."""
    pairs = dashboard.find_pairs(competition)
    assert [(p["approved"]["id"], p["rejected"]["id"]) for p in pairs] == [
        (PROOF_APPROVED, PROOF_REJECTED),
        ("20260902T150958Z-fe8c507ed1", "20260902T150958Z-b8f60bc82f"),
    ]
    for pair in pairs:
        assert pair["approved"]["config_version"] == pair["rejected"]["config_version"]
        assert pair["approved"]["as_of"] == pair["rejected"]["as_of"]
        assert pair["approved"]["id"].split("-")[0] == pair["as_of_second"]
        assert pair["approved_status"] == "filled"


def test_gbx10_proof_root_numbers_come_from_verdict_reason(competition):
    """GB-X-10: the brief's four figures, parsed from the governor's own reason."""
    rejected = next(r for r in list_roots(competition) if r["id"] == PROOF_REJECTED)
    numbers = dashboard.hero_numbers(rejected)
    assert numbers["computed_max_loss"] == 152584.00
    assert numbers["cap"] == 2000.00
    assert numbers["claimed_max_loss"] == 250.00
    assert numbers["claim_divergence"] == 152334.00
    assert numbers["approved"] is False
    assert numbers["failed_rules"] == ["max_loss_cap", "coverage", "cash_floor", "x_total_open_risk"]
    # Not recomputed: the figures are exactly what the reason text says.
    assert "computed_max_loss=152584.00" in rejected["verdict"]["reason"]
    assert "claim_divergence=152334.00" in rejected["verdict"]["reason"]


def test_gbx11_approved_twin_shows_no_divergence(competition):
    """GB-X-11: the approved root's claim matched the governor to the cent; its
    reason carries no figures, so they come from the max_loss_cap detail."""
    approved = next(r for r in list_roots(competition) if r["id"] == PROOF_APPROVED)
    numbers = dashboard.hero_numbers(approved)
    assert numbers["approved"] is True and numbers["failed_rules"] == []
    assert numbers["computed_max_loss"] == 411.0 and numbers["cap"] == 2000.0
    assert numbers["claimed_max_loss"] == 411.0 and numbers["claim_divergence"] == 0.0
    row = next(r for r in dashboard.root_rows(competition) if r["id"] == PROOF_APPROVED)
    assert row["claimed_max_loss"] == row["computed_max_loss"] == 411.0


def test_gbx12_unpaired_roots_are_not_pairs(dev):
    """GB-X-12: the dev sample's eight lone --no-submit roots pair with nothing;
    only its two adversarial runs do."""
    pairs = dashboard.find_pairs(dev)
    assert len(pairs) == 2
    assert {p["rejected"]["status"] for p in pairs} == {"governor_rejected"}
    assert dashboard.find_pairs([]) == []
    # Two dev roots share a hash suffix but not a second; they must not pair.
    seconds = [p["as_of_second"] for p in pairs]
    assert "20260902T161006Z" not in seconds and "20260902T161117Z" not in seconds


# ---------------------------------------------------------------------------
# GB-X-13..16 — replay
# ---------------------------------------------------------------------------

def test_gbx13_config_resolves_by_content_hash_not_name(competition):
    """GB-X-13: every competition root names the competition config's hash."""
    for root in list_roots(competition):
        path = dashboard.resolve_thresholds_path(root["config_version"])
        assert path is not None and path.name == "thresholds.competition.json"
    assert dashboard.resolve_thresholds_path("sha256:" + "0" * 64) is None
    assert dashboard.resolve_thresholds_path(None) is None
    assert dashboard.resolve_thresholds_path("v1") is None


def test_gbx14_every_competition_root_replays_matched(competition):
    """GB-X-14: the provenance claim, through the dashboard's own button path."""
    for root in list_roots(competition):
        result = dashboard.replay(root)
        assert result["replayable"] is True, result
        assert result["matched"] is True, (root["id"], result["differences"])
        assert result["thresholds_path"] == "config/thresholds.competition.json"


def test_gbx15_replay_refuses_to_guess_a_config(dev):
    """GB-X-15: the two oldest dev roots were decided under a thresholds file
    that no longer exists at this commit; the dashboard says so rather than
    replaying them under whatever is lying around."""
    roots = list_roots(dev)
    missing = [r for r in roots if dashboard.resolve_thresholds_path(r["config_version"]) is None]
    assert [r["id"] for r in missing] == ["20260902T133336Z-f5591959a5", "20260902T133336Z-bfa40f075c"]
    for root in missing:
        result = dashboard.replay(root)
        assert result["replayable"] is False and result["matched"] is None
        assert root["config_version"] in result["error"]
    for root in roots:
        if root not in missing:
            assert dashboard.replay(root)["matched"] is True, root["id"]


def test_gbx16_replay_is_read_only_and_a_follow_up_is_not_replayable(competition, tmp_path):
    """GB-X-16: replaying writes nothing, and a follow-up carries no verdict."""
    before = {p: p.read_bytes() for p in (REPO / "config").glob("*.json")}
    before[COMPETITION] = COMPETITION.read_bytes()
    follow_up = next(e for e in competition if e["root_id"] is not None)
    result = dashboard.replay(follow_up)
    assert result["replayable"] is False and "root entry" in result["error"]
    dashboard.replay(list_roots(competition)[0])
    assert all(p.read_bytes() == data for p, data in before.items())
    # A config edited on disk no longer hashes to the recorded version.
    tampered = tmp_path / "config"
    tampered.mkdir()
    doctored = json.loads((REPO / "config" / "thresholds.competition.json").read_text(encoding="utf-8"))
    doctored["cash_floor_pct"] = 0.0
    (tampered / "thresholds.competition.json").write_text(json.dumps(doctored), encoding="utf-8")
    root = list_roots(competition)[0]
    assert dashboard.resolve_thresholds_path(root["config_version"], ("config",), tmp_path) is None
    assert dashboard.replay(root, ("config",), tmp_path)["replayable"] is False
