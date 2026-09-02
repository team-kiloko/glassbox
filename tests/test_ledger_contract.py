"""GB-L — provenance ledger contract suite.

The audit record, per GB_INTERFACES.md shape 5 and 5a. Everything GlassBox claims
about itself — that a governed trade is reproducible, that no LLM sat in the risk
path, that a human did or did not confirm — is a claim about this file. If the
ledger is wrong or editable, the rest of the system is a demo.

Its non-negotiable behaviours:

  * **Append-only.** Entries are never mutated and never deleted. A correction is
    a new entry that references the id of the entry it corrects, and the wrong
    record stays in the file.
  * **`null` is a statement, absence is a bug.** `order` and `fill` are present
    and null when the pipeline stopped before them; an omitted key is
    indistinguishable from a truncated write.
  * **Chains fold by `root_id`**, not by adjacency, and `partial_fill` is not an
    end state.
  * **A verdict is reproducible.** The replay helper re-derives a root entry's
    verdict by re-running the governor on the entry's own embedded inputs. That
    is the provenance claim made executable rather than asserted in a README.

Two bands:

  GB-L-F**  fixture integrity — runs today, must pass. Guards the golden ledger.
  GB-L-**   ledger behaviour — xfail until glassbox/ledger.py lands, then runs
            for real automatically (see conftest.requires_ledger).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import (
    ENTRY_FIELDS,
    LEDGER,
    PROPOSED_STATUSES,
    ROOT_ONLY_FIELDS,
    SEAM_STATUSES,
    chain_of,
    requires_ledger,
    roots_of,
)

ALL_STATUSES = set(SEAM_STATUSES) | set(PROPOSED_STATUSES)
TERMINAL = {"governor_rejected", "broker_rejected", "filled", "expired", "canceled"}
IN_FLIGHT = {"approved_pending", "submitted", "partial_fill"}

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

#: The example prefixes named in the seam. They may appear in fixtures, clearly
#: marked; they may never appear in tracked module source.
EXAMPLE_PREFIXES = ("tkc-", "jho-")

PACKAGE = Path(__file__).resolve().parent.parent / "glassbox"


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Fixture integrity — runs today
# ---------------------------------------------------------------------------

def test_gb_l_f01_every_entry_is_a_complete_shape_5_record(entries, ledger_lines):
    """GB-L-F01: every line is one entry with the full field set, in canonical order.

    Not "has at least these keys": exactly these, in exactly this order. The key
    order is the serialization contract, and a field quietly added or dropped is
    the failure mode an audit file cannot survive.
    """
    assert len(entries) == len(ledger_lines), "one entry per line, no blanks"
    for entry in entries:
        assert tuple(entry) == ENTRY_FIELDS, (
            f"{entry.get('id')}: fields are {tuple(entry)}, expected {ENTRY_FIELDS}"
        )
        assert entry["status"] in ALL_STATUSES, f"{entry['id']}: {entry['status']}"
        for field in ("ts", "as_of"):
            assert ISO_UTC.match(entry[field]), f"{entry['id']}.{field}={entry[field]}"
        assert isinstance(entry["code_version"], str) and entry["code_version"]
        assert entry["mode"] in ("approve", "autopilot")
        assert entry["config_version"].startswith("sha256:")


def test_gb_l_f02_roots_and_follow_ups_carry_the_right_payloads(entries, entry_by_id):
    """GB-L-F02: a root carries the decision; a follow-up carries the transition.

    And every entry states every key either way — `null` is the positive
    statement that the pipeline reached here and stopped (shape 5).
    """
    for entry in entries:
        is_root = entry["root_id"] is None
        for field in ROOT_ONLY_FIELDS:
            if is_root:
                assert isinstance(entry[field], dict) and entry[field], (
                    f"{entry['id']}: a root entry carries its {field}"
                )
            else:
                assert entry[field] is None, (
                    f"{entry['id']}: a follow-up restates no {field}; null, not omitted"
                )
        if is_root:
            assert entry["order"] is None and entry["fill"] is None, (
                f"{entry['id']}: the root is written PRE-submission (5a)"
            )
        else:
            assert entry["root_id"] in entry_by_id, f"{entry['id']}: dangling root_id"
            assert entry_by_id[entry["root_id"]]["root_id"] is None, (
                f"{entry['id']}: root_id must point at a ROOT, not another follow-up"
            )

    # Rejections are terminal at the root and never grow a follow-up.
    for root in roots_of(entries):
        if root["status"] == "governor_rejected":
            assert chain_of(entries, root["id"]) == [root], (
                f"{root['id']}: a governor rejection built no order, so there is "
                f"nothing for a follow-up to report"
            )


def test_gb_l_f03_chains_fold_by_root_id_and_are_not_contiguous(
    entries, expected_chains
):
    """GB-L-F03: the golden fold is right, and the file really does interleave.

    If the fixtures happened to be contiguous per chain, a wrong implementation
    would pass GB-L-08 by accident. This asserts the trap is actually set.
    """
    chains = expected_chains["chains"]
    assert {r["id"] for r in roots_of(entries)} == set(chains), "golden covers every root"

    for root_id, expected in chains.items():
        folded = chain_of(entries, root_id)
        assert [e["id"] for e in folded] == expected["entry_ids"], root_id
        assert folded[0]["id"] == root_id, "the root leads its own chain"
        assert folded[-1]["status"] == expected["status"], root_id
        assert (expected["status"] in TERMINAL) is expected["terminal"], root_id

        ts_values = [_ts(e["ts"]) for e in folded]
        assert ts_values == sorted(ts_values), f"{root_id}: chain runs backwards"
        assert len({e["as_of"] for e in folded}) == 1, (
            f"{root_id}: one decision, one as_of — ts moves, as_of does not"
        )

    interleaved = any(
        not _is_contiguous(entries, root_id) for root_id in chains
    )
    assert interleaved, (
        "the golden file must interleave at least one chain, or a fold that "
        "assumes adjacency passes by luck"
    )

    assert set(expected_chains["terminal_statuses"]) == TERMINAL
    assert set(expected_chains["in_flight_statuses"]) == IN_FLIGHT
    assert "partial_fill" in IN_FLIGHT, "partial_fill is NON-TERMINAL (5a)"


def _is_contiguous(entries, root_id):
    positions = [i for i, e in enumerate(entries) if (e["root_id"] or e["id"]) == root_id]
    return positions == list(range(positions[0], positions[-1] + 1))


def test_gb_l_f04_provenance_fields_say_what_they_mean(entries, expected_chains):
    """GB-L-F04: autopilot records no approver; a null prompt_version is a null."""
    autopilot_roots = set(expected_chains["autopilot_roots"])
    null_prompt_roots = set(expected_chains["null_prompt_roots"])
    assert autopilot_roots and null_prompt_roots, "keep both cases in the fixtures"

    for entry in entries:
        if entry["mode"] == "autopilot":
            assert entry["approved_by"] is None and entry["approved_at"] is None, (
                f"{entry['id']}: autopilot means no human confirmed — a recorded "
                f"fact, not a gap"
            )
        if entry["approved_at"] is not None:
            assert ISO_UTC.match(entry["approved_at"])
            assert entry["approved_by"], "an approval time with no approver"

    for root_id in autopilot_roots:
        for entry in chain_of(entries, root_id):
            assert entry["mode"] == "autopilot", "mode rides the whole chain"
    for root_id in null_prompt_roots:
        for entry in chain_of(entries, root_id):
            assert entry["prompt_version"] is None, (
                "no LLM produced this proposal: null, not '' and not 'none'"
            )
    assert any(e["prompt_version"] for e in entries), "keep an LLM-produced case too"


def test_gb_l_f05_embedded_verdicts_match_the_governor_golden(
    entries, expected_chains, gov_golden
):
    """GB-L-F05: the embedded verdicts are the GOVERNOR's hand-authored golden.

    This is where the circularity stops. The ledger entries were generated by
    running the real governor, so on their own they prove nothing about the
    governor. Cross-checking each embedded verdict against the GB-C golden's
    hand-authored `checks` map means these fixtures cannot drift from the
    governor's contract without a test going red.
    """
    for root_id, chain in expected_chains["chains"].items():
        root = next(e for e in entries if e["id"] == root_id)
        case = gov_golden["cases"][chain["gb_c_case"]]
        verdict = root["verdict"]

        assert verdict["approved"] is case["approved"], root_id
        assert {c["rule"]: c["passed"] for c in verdict["checks"]} == case["checks"], (
            f"{root_id}: embedded verdict disagrees with GB-C golden "
            f"{chain['gb_c_case']}"
        )
        assert verdict["mode"] == root["mode"]
        assert verdict["config_version"] == root["config_version"]
        assert "prompt_version" not in verdict, (
            "the governor is deterministic and has no prompt (shape 3); the "
            "prompt version lives on the ledger entry"
        )
        # The status the root was written with follows from the verdict.
        expected_status = "approved_pending" if verdict["approved"] else "governor_rejected"
        assert root["status"] == expected_status, root_id


def test_gb_l_f06_corrections_append_and_never_edit(entries, expected_chains, entry_by_id):
    """GB-L-F06: the corrected entry is still in the file, unchanged."""
    corrections = expected_chains["corrections"]
    assert corrections, "keep at least one correction in the fixtures"

    for correction_id, corrected_id in corrections.items():
        correction = entry_by_id[correction_id]
        corrected = entry_by_id[corrected_id]
        assert correction["corrects"] == corrected_id
        assert corrected["corrects"] is None
        assert correction["root_id"] == corrected["root_id"], (
            "a correction stays in the chain it corrects"
        )
        assert _ts(correction["ts"]) > _ts(corrected["ts"])
        assert correction["order"] != corrected["order"], (
            "a correction that changes nothing is not a correction"
        )

    non_corrections = [e for e in entries if e["corrects"] is None]
    assert len(non_corrections) == len(entries) - len(corrections)
    for entry in entries:
        assert "corrects" in entry, "present on every entry, null on most"


def test_gb_l_f07_client_order_ids_are_prefix_plus_root_id(entries, entry_by_id):
    """GB-L-F07: every order id in the fixtures is <prefix><root entry id> (shape 4).

    The prefix VALUE is not asserted — it is configuration, and the fixture
    renders one only as a marked example. The structure is asserted, because that
    is what gives idempotency at the broker on a retried submit.
    """
    seen = 0
    for entry in entries:
        order = entry["order"]
        if not order:
            continue
        seen += 1
        root_id = entry["root_id"] or entry["id"]
        client_order_id = order["client_order_id"]
        assert client_order_id.endswith(root_id), (
            f"{entry['id']}: client_order_id must embed the ROOT entry id so a "
            f"retried submit dedupes at the broker"
        )
        prefix = client_order_id[: -len(root_id)]
        assert prefix, "there is a prefix, and it comes from the environment"
        assert entry_by_id[root_id]["root_id"] is None
    assert seen, "the fixtures must carry order payloads"


# ---------------------------------------------------------------------------
# Ledger behaviour — xfail until the module lands
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_ledger(tmp_path):
    return tmp_path / "ledger.jsonl"


@pytest.fixture()
def root_kwargs(entries):
    """A fresh root entry's fields, taken from the golden decision entry."""
    root = next(e for e in entries if e["status"] == "approved_pending")
    return {field: root[field] for field in ENTRY_FIELDS if field not in ("root_id", "corrects")}


@requires_ledger
def test_gb_l_01_the_writer_has_no_update_and_no_delete(tmp_ledger, root_kwargs):
    """GB-L-01: append-only is enforced by the API, not by convention.

    `update` and `delete` exist and raise, on purpose: the prohibition is
    documented where someone reaching for it will find it, rather than left to an
    AttributeError that reads like an oversight.
    """
    ledger = LEDGER.Ledger(tmp_ledger)
    ledger.append_root(**root_kwargs)

    for method in ("update", "delete"):
        assert hasattr(ledger, method), (
            f"{method}() should exist and refuse, so the rule is discoverable"
        )
        with pytest.raises(LEDGER.AppendOnlyError):
            getattr(ledger, method)(root_kwargs["id"], {"status": "filled"})

    # And nothing else on the class quietly mutates.
    for name in dir(ledger):
        if name.startswith("_"):
            continue
        assert not any(
            verb in name for verb in ("rewrite", "overwrite", "remove", "truncate", "edit")
        ), f"Ledger.{name} looks like a mutation"


@requires_ledger
def test_gb_l_02_order_and_fill_are_present_as_null(tmp_ledger, root_kwargs):
    """GB-L-02: never key-omitted. An absent key is a corrupted record."""
    ledger = LEDGER.Ledger(tmp_ledger)
    entry = ledger.append_root(**root_kwargs)

    assert entry["order"] is None and entry["fill"] is None
    line = json.loads(tmp_ledger.read_text().splitlines()[0])
    assert "order" in line and "fill" in line
    assert line["order"] is None and line["fill"] is None


@requires_ledger
def test_gb_l_03_every_entry_carries_the_full_provenance_block(
    tmp_ledger, root_kwargs, entries
):
    """GB-L-03: id, ts, as_of, mode, status, the three versions, and the approver pair.

    On follow-ups too. Six weeks later the question is what data, what config,
    what prompt, what code, and who said yes — and it has to be answerable from
    any single line.
    """
    ledger = LEDGER.Ledger(tmp_ledger)
    root = ledger.append_root(**root_kwargs)
    follow_up = ledger.append_follow_up(
        id="follow-1", root_id=root["id"], ts="2026-09-02T15:30:07Z",
        status="submitted", order={"client_order_id": "x-" + root["id"]}, fill=None,
    )

    for entry in (root, follow_up):
        assert tuple(entry) == ENTRY_FIELDS
        for field in ("id", "ts", "as_of", "mode", "status", "config_version",
                      "code_version"):
            assert entry[field] is not None, f"{field} must be stated"
        for field in ("prompt_version", "approved_by", "approved_at"):
            assert field in entry
    # Provenance rides the chain: a follow-up inherits the root's block.
    for field in ("as_of", "mode", "config_version", "prompt_version",
                  "code_version", "approved_by", "approved_at"):
        assert follow_up[field] == root[field], f"{field} must ride the chain"


@requires_ledger
def test_gb_l_04_prompt_version_is_null_when_no_llm_produced_the_proposal(
    tmp_ledger, root_kwargs
):
    """GB-L-04: a hand-authored proposal records null, not a placeholder string."""
    ledger = LEDGER.Ledger(tmp_ledger)
    entry = ledger.append_root(**{**root_kwargs, "prompt_version": None})
    assert entry["prompt_version"] is None
    assert '"prompt_version": null' in tmp_ledger.read_text()

    for placeholder in ("", "none", "n/a"):
        with pytest.raises(ValueError):
            LEDGER.Ledger(tmp_ledger).append_root(
                **{**root_kwargs, "id": "x", "prompt_version": placeholder}
            )


@requires_ledger
def test_gb_l_05_autopilot_records_no_approver(tmp_ledger, root_kwargs):
    """GB-L-05: approved_by/approved_at are null in autopilot, and that is enforced.

    A ledger that let an autopilot run name an approver would let the system
    claim a human was in the loop when none was.
    """
    ledger = LEDGER.Ledger(tmp_ledger)
    entry = ledger.append_root(
        **{**root_kwargs, "mode": "autopilot", "approved_by": None, "approved_at": None}
    )
    assert entry["approved_by"] is None and entry["approved_at"] is None

    with pytest.raises(ValueError):
        LEDGER.Ledger(tmp_ledger).append_root(
            **{**root_kwargs, "id": "x", "mode": "autopilot",
               "approved_by": "teakeycee", "approved_at": "2026-09-02T15:30:00Z"}
        )


@requires_ledger
def test_gb_l_06_client_order_id_is_prefix_plus_root_id(monkeypatch):
    """GB-L-06: <ORDER_ID_PREFIX><ledger-entry-id>, prefix read from the environment."""
    monkeypatch.setenv("ORDER_ID_PREFIX", "zzz-")
    assert LEDGER.client_order_id("root-123") == "zzz-root-123"

    # An explicitly supplied environment works too, so a caller need not mutate
    # the process to build an id.
    assert LEDGER.client_order_id("root-123", env={"ORDER_ID_PREFIX": "qqq-"}) == "qqq-root-123"


@requires_ledger
def test_gb_l_07_a_missing_prefix_raises_and_none_is_hardcoded(monkeypatch):
    """GB-L-07: unset prefix raises; no prefix literal in the package source.

    CLAUDE.md and shape 4 both say it: the prefix is configuration, never a
    constant, and the builder fails rather than guessing. A default would put
    tkc- on Jhoosier's orders on the shared account.
    """
    monkeypatch.delenv("ORDER_ID_PREFIX", raising=False)
    with pytest.raises(ValueError):
        LEDGER.client_order_id("root-123")

    monkeypatch.setenv("ORDER_ID_PREFIX", "")
    with pytest.raises(ValueError):
        LEDGER.client_order_id("root-123")
    with pytest.raises(ValueError):
        LEDGER.client_order_id("root-123", env={})

    for source in PACKAGE.glob("*.py"):
        text = source.read_text()
        for prefix in EXAMPLE_PREFIXES:
            assert prefix not in text, (
                f"{source.name} contains the literal {prefix!r}: the order id "
                f"prefix is configuration, never a constant in tracked code"
            )


@requires_ledger
def test_gb_l_08_folds_a_chain_by_root_id(entries, expected_chains):
    """GB-L-08: given a root id, the ordered chain — across interleaved entries."""
    for root_id, expected in expected_chains["chains"].items():
        chain = LEDGER.fold_chain(entries, root_id)
        assert [e["id"] for e in chain["entries"]] == expected["entry_ids"], root_id
        assert chain["root_id"] == root_id
        assert chain["entries"][0]["root_id"] is None

    assert {r["id"] for r in LEDGER.list_roots(entries)} == set(expected_chains["chains"])

    with pytest.raises(KeyError):
        LEDGER.fold_chain(entries, "no-such-root")


@requires_ledger
def test_gb_l_09_current_status_knows_partial_fill_is_not_an_end_state(
    entries, expected_chains
):
    """GB-L-09: terminal vs in-flight, and partial_fill is in-flight (5a).

    Alpaca's partially_filled is not an end state. A terminal-only vocabulary
    files a live order as finished, and the dashboard then shows a position that
    is still working as done.
    """
    for root_id, expected in expected_chains["chains"].items():
        status, terminal = LEDGER.current_status(entries, root_id)
        assert status == expected["status"], root_id
        assert terminal is expected["terminal"], root_id

    in_flight = [r for r, c in expected_chains["chains"].items() if not c["terminal"]]
    assert in_flight, "keep an in-flight chain in the fixtures"
    for root_id in in_flight:
        assert LEDGER.current_status(entries, root_id)[0] == "partial_fill"
    assert LEDGER.is_terminal("partial_fill") is False
    assert LEDGER.is_terminal("filled") is True


@requires_ledger
def test_gb_l_10_a_governor_rejection_is_complete_at_the_root(entries):
    """GB-L-10: the rejection entry carries the whole verdict and needs no follow-up.

    The rejections are the entries most worth keeping: they are the evidence the
    governor did its job. A rejection recorded as a bare status is not evidence.
    """
    rejected = [e for e in entries if e["status"] == "governor_rejected"]
    assert rejected, "keep a rejection in the fixtures"

    for entry in rejected:
        chain = LEDGER.fold_chain(entries, entry["id"])
        assert len(chain["entries"]) == 1
        assert chain["terminal"] is True
        assert entry["order"] is None and entry["fill"] is None

        verdict = entry["verdict"]
        assert verdict["approved"] is False
        assert verdict["checks"], "the full checks[] is embedded, not a summary"
        failed = [c for c in verdict["checks"] if not c["passed"]]
        assert failed and all(c["detail"].strip() for c in verdict["checks"]), (
            "every check keeps its detail, including the ones that passed"
        )
        assert entry["proposal"] and entry["snapshot"], (
            "the inputs stay with the decision, or it cannot be replayed"
        )


@requires_ledger
def test_gb_l_11_serialization_is_deterministic_and_byte_stable(
    tmp_ledger, entries, ledger_lines
):
    """GB-L-11: two writes of the same entry are byte-identical, and match the golden.

    The golden file IS the format spec. A diff of a ledger has to mean a change
    in the facts, not a change in dict ordering or float formatting.
    """
    for entry, line in zip(entries, ledger_lines):
        assert LEDGER.serialize(entry) == line, f"{entry['id']}: serialization drift"
        assert LEDGER.serialize(entry) == LEDGER.serialize(entry)
        assert LEDGER.deserialize(line) == entry

    # Key order is the shape 5 order, not insertion order and not luck.
    shuffled = {k: entries[0][k] for k in reversed(ENTRY_FIELDS)}
    assert LEDGER.serialize(shuffled) == ledger_lines[0], (
        "the writer imposes canonical key order; the caller's dict order is irrelevant"
    )

    # Timestamps normalise to ISO-8601 UTC with a Z, whatever the caller hands in.
    aware = datetime(2026, 9, 2, 15, 30, 5, tzinfo=timezone.utc)
    assert LEDGER.iso_utc(aware) == "2026-09-02T15:30:05Z"
    assert LEDGER.iso_utc("2026-09-02T11:30:05-04:00") == "2026-09-02T15:30:05Z"
    with pytest.raises(ValueError):
        LEDGER.iso_utc(datetime(2026, 9, 2, 15, 30, 5))  # naive


@requires_ledger
def test_gb_l_12_storage_is_a_caller_supplied_path_with_no_global_state(
    tmp_path, root_kwargs
):
    """GB-L-12: two ledgers at two paths do not know about each other.

    No module-level file handle, no default path, no process-wide singleton — the
    caller owns the storage, exactly as the caller owns the config.
    """
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    ledger_a, ledger_b = LEDGER.Ledger(first), LEDGER.Ledger(second)

    ledger_a.append_root(**root_kwargs)
    ledger_b.append_root(**{**root_kwargs, "id": "other-root"})

    assert len(first.read_text().splitlines()) == 1
    assert len(second.read_text().splitlines()) == 1
    assert LEDGER.load(first)[0]["id"] == root_kwargs["id"]
    assert LEDGER.load(second)[0]["id"] == "other-root"

    # One entry, one line, newline-terminated: the file stays greppable and any
    # partial write is visible as a broken last line rather than silent damage.
    assert first.read_text().endswith("\n")
    assert "\n" not in first.read_text()[:-1]


@requires_ledger
def test_gb_l_13_the_writer_holds_no_clock(tmp_ledger, root_kwargs):
    """GB-L-13: `ts` is passed in. The writer never asks what time it is.

    Same discipline as the screener's as_of and the governor's clock: a component
    that reads the wall clock cannot be replayed, and this one writes the record
    replay depends on.
    """
    import inspect

    source = inspect.getsource(LEDGER)
    for forbidden in ("datetime.now", "datetime.utcnow", "time.time", "time.monotonic"):
        assert forbidden not in source, f"the ledger writer called {forbidden}"

    with pytest.raises(TypeError):
        LEDGER.Ledger(tmp_ledger).append_root(
            **{k: v for k, v in root_kwargs.items() if k != "ts"}
        )


@requires_ledger
def test_gb_l_14_a_correction_appends_and_leaves_the_original_intact(
    tmp_ledger, root_kwargs
):
    """GB-L-14: the wrong record stays in the file; the right one points at it."""
    ledger = LEDGER.Ledger(tmp_ledger)
    root = ledger.append_root(**root_kwargs)
    wrong = ledger.append_follow_up(
        id="fu-1", root_id=root["id"], ts="2026-09-02T15:40:06Z",
        status="broker_rejected", order={"reject_reason": "wrong reason"}, fill=None,
    )
    before = tmp_ledger.read_text()

    correction = ledger.append_correction(
        id="fu-2", corrects=wrong["id"], root_id=root["id"],
        ts="2026-09-02T15:52:11Z", status="broker_rejected",
        order={"reject_reason": "the real reason"}, fill=None,
    )

    assert correction["corrects"] == wrong["id"]
    assert correction["root_id"] == root["id"]
    after = tmp_ledger.read_text()
    assert after.startswith(before), "prior bytes are untouched — this is append-only"
    assert len(after.splitlines()) == 3

    entries = LEDGER.load(tmp_ledger)
    assert entries[1] == wrong, "the corrected entry is still there, verbatim"
    assert [e["id"] for e in LEDGER.fold_chain(entries, root["id"])["entries"]] == [
        root["id"], "fu-1", "fu-2"
    ]

    # A correction must point at an entry that exists.
    with pytest.raises(ValueError):
        ledger.append_correction(
            id="fu-3", corrects="no-such-entry", root_id=root["id"],
            ts="2026-09-02T15:53:00Z", status="broker_rejected", order=None, fill=None,
        )


@requires_ledger
def test_gb_l_15_replay_reproduces_the_verdict_from_the_entry_alone(
    entries, gov_thresholds
):
    """GB-L-15: THE provenance claim, executable.

    Re-run the governor on the entry's own embedded proposal, account state and
    clock, and get the recorded verdict back. Nothing outside the ledger entry is
    consulted except the config the entry names. If this passes, "auditable" is a
    property of the system rather than a word in the write-up.
    """
    roots = [e for e in entries if e["root_id"] is None]
    assert roots

    for root in roots:
        result = LEDGER.replay_root(root, gov_thresholds)
        assert result["matched"] is True, (
            f"{root['id']} does not replay: {result['differences']}"
        )
        assert result["verdict"] == root["verdict"]
        assert not result["differences"]

    # And the strict form, which raises rather than reporting.
    for root in roots:
        assert LEDGER.assert_replays(root, gov_thresholds) == root["verdict"]


@requires_ledger
def test_gb_l_16_replay_catches_a_doctored_ledger(entries, gov_thresholds):
    """GB-L-16: replay that cannot fail proves nothing.

    Flip the recorded verdict of the rejection to approved — the single most
    valuable edit an attacker or a bug could make — and replay must refuse it and
    say where it diverged.
    """
    rejection = next(e for e in entries if e["status"] == "governor_rejected")
    tampered = json.loads(json.dumps(rejection))
    tampered["verdict"]["approved"] = True
    for check in tampered["verdict"]["checks"]:
        check["passed"] = True

    result = LEDGER.replay_root(tampered, gov_thresholds)
    assert result["matched"] is False
    assert result["differences"], "a mismatch must say what differed"
    assert any("approved" in str(d) for d in result["differences"])

    with pytest.raises(LEDGER.ReplayMismatch):
        LEDGER.assert_replays(tampered, gov_thresholds)

    # A doctored INPUT is caught the same way: change the proposal and the
    # recorded verdict no longer follows from it.
    swapped = json.loads(json.dumps(rejection))
    swapped["proposal"]["claimed_max_loss"] = 819
    swapped["proposal"]["legs"][0]["limit_price"] = 1.00
    assert LEDGER.replay_root(swapped, gov_thresholds)["matched"] is False


@requires_ledger
def test_gb_l_17_replay_refuses_a_config_it_was_not_run_under(entries, gov_thresholds):
    """GB-L-17: replaying under a different config is not a reproduction.

    `config_version` identifies exactly which thresholds produced the verdict
    (shape 3). Replaying against a different config and calling a match a
    reproduction would be the audit trail lying in the most convincing way
    available to it.
    """
    root = next(e for e in entries if e["root_id"] is None)
    assert LEDGER.replay_root(root, gov_thresholds,
                              config_version=root["config_version"])["matched"] is True

    with pytest.raises(ValueError):
        LEDGER.replay_root(root, gov_thresholds, config_version="sha256:something-else")


@requires_ledger
def test_gb_l_18_round_trips_and_rejects_unknown_statuses(tmp_ledger, root_kwargs):
    """GB-L-18: what is written is what is read, and the vocabulary stays closed.

    Adding a status value is a seam change (shape 5). The writer refuses one it
    was not given, so the vocabulary cannot grow by accident in a crunch.
    """
    ledger = LEDGER.Ledger(tmp_ledger)
    written = ledger.append_root(**root_kwargs)
    assert LEDGER.load(tmp_ledger) == [written]

    assert set(LEDGER.SEAM_STATUSES) == set(SEAM_STATUSES)
    assert set(LEDGER.PROPOSED_STATUSES) == set(PROPOSED_STATUSES)

    for bad in ("done", "partially_filled", "APPROVED_PENDING", ""):
        with pytest.raises(ValueError):
            LEDGER.Ledger(tmp_ledger).append_root(
                **{**root_kwargs, "id": "x", "status": bad}
            )


@requires_ledger
def test_gb_l_19_a_follow_up_cannot_invent_a_root(tmp_ledger, root_kwargs):
    """GB-L-19: chains cannot be orphaned or forked at write time.

    A follow-up whose root is not in this file, or whose root_id points at
    another follow-up, would break the fold and hide a position from the
    dashboard.
    """
    ledger = LEDGER.Ledger(tmp_ledger)
    root = ledger.append_root(**root_kwargs)
    follow_up = ledger.append_follow_up(
        id="fu-1", root_id=root["id"], ts="2026-09-02T15:30:07Z",
        status="submitted", order=None, fill=None,
    )

    with pytest.raises(ValueError):
        ledger.append_follow_up(
            id="fu-2", root_id="ghost-root", ts="2026-09-02T15:30:08Z",
            status="submitted", order=None, fill=None,
        )
    with pytest.raises(ValueError):
        ledger.append_follow_up(
            id="fu-3", root_id=follow_up["id"], ts="2026-09-02T15:30:09Z",
            status="submitted", order=None, fill=None,
        )
    # A duplicate id would make the chain ambiguous.
    with pytest.raises(ValueError):
        ledger.append_follow_up(
            id="fu-1", root_id=root["id"], ts="2026-09-02T15:30:10Z",
            status="filled", order=None, fill=None,
        )


@requires_ledger
def test_gb_l_20_the_golden_file_loads_and_folds_end_to_end(
    ledger_path, expected_chains, gov_thresholds
):
    """GB-L-20: the whole golden ledger, through the module, exactly as the dashboard will.

    Load the file, list the roots, fold every chain, read every current status,
    and replay every decision. This is the acceptance criterion for "the ledger
    works", stated once against the real artefact.
    """
    entries = LEDGER.load(ledger_path)
    assert len(entries) == 18

    roots = LEDGER.list_roots(entries)
    assert {r["id"] for r in roots} == set(expected_chains["chains"])

    folded_ids = []
    for root in roots:
        chain = LEDGER.fold_chain(entries, root["id"])
        expected = expected_chains["chains"][root["id"]]
        assert [e["id"] for e in chain["entries"]] == expected["entry_ids"]
        assert chain["status"] == expected["status"]
        assert chain["terminal"] is expected["terminal"]
        assert LEDGER.assert_replays(root, gov_thresholds) == root["verdict"]
        folded_ids += expected["entry_ids"]

    # Every entry belongs to exactly one chain: nothing is orphaned or double-counted.
    assert sorted(folded_ids) == sorted(e["id"] for e in entries)
