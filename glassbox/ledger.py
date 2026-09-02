"""Provenance ledger — GB_INTERFACES.md shape 5 and 5a.

The audit record. Everything GlassBox claims about itself — that a governed
trade is reproducible, that no language model sat in the risk path, that a human
did or did not confirm — is a claim about this file. If the ledger is wrong or
editable, the rest of the system is a demo with good intentions.

Four properties, in the order they matter:

1. **Append-only.** Entries are never mutated and never deleted. A correction is
   a new entry carrying `corrects`, the id of the entry it corrects; the wrong
   record stays in the file. ``update()`` and ``delete()`` exist and raise, so
   the prohibition is discoverable where someone reaches for it rather than left
   to an AttributeError that reads like an oversight.
2. **`null` is a statement; a missing key is a bug.** Every entry carries every
   field of shape 5. `order` and `fill` are null when the pipeline stopped before
   them, and that null is a positive statement that it reached this point and
   went no further.
3. **Chains fold by `root_id`,** never by adjacency — entries from different
   chains interleave in any real run — and `partial_fill` is not an end state.
4. **A verdict is reproducible.** :func:`replay_root` re-derives a root entry's
   verdict by re-running the governor on the entry's own embedded inputs, and
   :func:`assert_replays` raises if it differs. That is the provenance claim made
   executable rather than asserted in a write-up.

Purity, where it applies: **the writer holds no clock** — `ts` is passed in, the
same discipline as the screener's `as_of` and the governor's clock, and for the
same reason: a component that reads the wall clock cannot be replayed, and this
one writes the record replay depends on. **Storage is a caller-supplied path**
with no module-level state, no default location, and no process-wide singleton.
Serialization is deterministic: shape 5 key order at the top level, sorted keys
below it, ISO-8601 UTC timestamps, one entry per line. Two writes of the same
entry are byte-identical, which is what lets a diff of a ledger mean a change in
the facts.

Three things shape 5 leaves open are decided here, marked **PROPOSED** and
written up in ``tests/fixtures/ledger/README.md`` for both humans:
``approved_pending`` as the root status, ``corrects`` as a nullable field, and
the composition of ``snapshot``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "Ledger", "AppendOnlyError", "ReplayMismatch",
    "ENTRY_FIELDS", "SEAM_STATUSES", "PROPOSED_STATUSES", "STATUSES",
    "TERMINAL_STATUSES", "IN_FLIGHT_STATUSES",
    "serialize", "deserialize", "iso_utc", "load",
    "list_roots", "fold_chain", "current_status", "is_terminal",
    "client_order_id", "replay_root", "assert_replays",
]

#: Shape 5's field order, with `corrects` (PROPOSED) seated next to `root_id`.
#: This IS the canonical serialization order.
ENTRY_FIELDS = (
    "id", "root_id", "corrects", "ts", "as_of", "mode", "status",
    "config_version", "prompt_version", "code_version",
    "approved_by", "approved_at", "snapshot", "proposal", "verdict",
    "order", "fill",
)

#: Shape 5's status vocabulary. Adding a value is a seam change.
SEAM_STATUSES = (
    "governor_rejected", "submitted", "broker_rejected", "filled",
    "partial_fill", "expired", "canceled",
)

#: PROPOSED, pending both humans: 5a requires the root decision entry to be
#: written PRE-submission, and the seam vocabulary has no value for "approved,
#: not yet submitted" — every value it does have describes a rejection or a state
#: an order is already in.
PROPOSED_STATUSES = ("approved_pending",)

STATUSES = SEAM_STATUSES + PROPOSED_STATUSES

#: `partial_fill` is deliberately NOT terminal: Alpaca's partially_filled is not
#: an end state, and a chain sitting on one may still reach filled, expired or
#: canceled (5a).
TERMINAL_STATUSES = frozenset(
    {"governor_rejected", "broker_rejected", "filled", "expired", "canceled"}
)
IN_FLIGHT_STATUSES = frozenset({"approved_pending", "submitted", "partial_fill"})

#: Fields the root decision entry carries and a follow-up does not.
_ROOT_ONLY_FIELDS = ("snapshot", "proposal", "verdict")

_ORDER_ID_PREFIX_ENV = "ORDER_ID_PREFIX"


class AppendOnlyError(RuntimeError):
    """Raised for any attempt to mutate or delete a ledger entry."""


class ReplayMismatch(AssertionError):
    """Raised when a recorded verdict does not follow from its own inputs."""


# ---------------------------------------------------------------------------
# Serialization — deterministic by construction
# ---------------------------------------------------------------------------

def iso_utc(value):
    """Normalise a timestamp to ISO-8601 UTC with a `Z`.

    Accepts an aware datetime or an ISO-8601 string. A naive datetime raises:
    an audit timestamp with no zone is a timestamp that means something
    different on the other pod's machine.
    """
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"not an ISO-8601 timestamp: {value!r}") from None
    else:
        raise ValueError(f"timestamp must be a datetime or ISO-8601 string: {value!r}")

    if stamp.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value):
    """Recursively impose a stable key order below the top level."""
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def serialize(entry):
    """One JSONL line. Byte-identical for equal entries, whatever their key order."""
    missing = [field for field in ENTRY_FIELDS if field not in entry]
    if missing:
        raise ValueError(
            "entry is missing " + ", ".join(missing)
            + " — every field of shape 5 is present on every entry, null where it "
            "does not apply; an omitted key is indistinguishable from a truncated "
            "write"
        )
        
    extra = [key for key in entry if key not in ENTRY_FIELDS]
    if extra:
        raise ValueError(f"entry carries unknown field(s): {', '.join(extra)}")

    ordered = {}
    for field in ENTRY_FIELDS:
        value = entry[field]
        ordered[field] = _canonical(value) if field in (
            "snapshot", "proposal", "verdict", "order", "fill"
        ) else value
    return json.dumps(ordered, ensure_ascii=False, allow_nan=False)


def deserialize(line):
    return json.loads(line)


def load(path):
    """Every entry in the file, in append order."""
    text = Path(path).read_text(encoding="utf-8")
    return [deserialize(line) for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

class Ledger:
    """An append-only JSONL ledger at a caller-supplied path.

    Holds no clock, no config, and no process-wide state: two Ledger objects at
    two paths know nothing about each other.
    """

    def __init__(self, path):
        self.path = Path(path)

    # -- the only three ways to write -------------------------------------

    def append_root(self, *, id, ts, as_of, mode, status, config_version,
                    prompt_version, code_version, approved_by, approved_at,
                    snapshot, proposal, verdict, order=None, fill=None):
        """The decision entry, written PRE-submission (5a).

        `root_id` is null — a root entry is its own root — and `order` / `fill`
        must be null because no order exists yet. Its `id` is what
        `client_order_id` embeds, which is why it must be written first.

        `order` and `fill` are accepted rather than silently supplied so that a
        caller round-tripping an entry through this writer states every field of
        shape 5, as the file itself does. Passing anything but null for either is
        a caller error: an order that existed before the decision entry could not
        have carried that entry's id.
        """
        if order is not None or fill is not None:
            raise ValueError(
                "a root entry is written PRE-submission (5a): order and fill are "
                "null, and the order that follows embeds this entry's id"
            )
        entry = _build(
            id=id, root_id=None, corrects=None, ts=ts, as_of=as_of, mode=mode,
            status=status, config_version=config_version,
            prompt_version=prompt_version, code_version=code_version,
            approved_by=approved_by, approved_at=approved_at,
            snapshot=snapshot, proposal=proposal, verdict=verdict,
            order=None, fill=None,
        )
        for field in _ROOT_ONLY_FIELDS:
            if not entry[field]:
                raise ValueError(
                    f"a root entry carries its {field}: without it the decision "
                    f"cannot be replayed, and an unreplayable decision is not a "
                    f"provenance record"
                )
        return self._append(entry)

    def append_follow_up(self, *, id, root_id, ts, status, order, fill,
                         corrects=None):
        """A transition: submission, fill, partial fill, rejection, cancel, expiry.

        The provenance block rides the chain — as_of, mode, the three versions and
        the approver pair are read from the root, not restated by the caller, so
        they cannot drift within a chain.
        """
        entries = self._existing()
        root = _require_root(entries, root_id)
        _require_unique(entries, id)
        if corrects is not None:
            _require_entry(entries, corrects)

        entry = _build(
            id=id, root_id=root_id, corrects=corrects, ts=ts,
            as_of=root["as_of"], mode=root["mode"], status=status,
            config_version=root["config_version"],
            prompt_version=root["prompt_version"],
            code_version=root["code_version"],
            approved_by=root["approved_by"], approved_at=root["approved_at"],
            snapshot=None, proposal=None, verdict=None, order=order, fill=fill,
        )
        return self._append(entry)

    def append_correction(self, *, id, corrects, root_id, ts, status, order, fill):
        """A correction: a new entry referencing the id of the entry it corrects.

        The corrected entry is untouched and stays in the file. There is no
        in-place update anywhere in this system, and a correction that removed
        the record it corrects would destroy the evidence it exists to preserve.
        """
        if corrects is None:
            raise ValueError("a correction must name the entry it corrects")
        return self.append_follow_up(
            id=id, root_id=root_id, ts=ts, status=status, order=order, fill=fill,
            corrects=corrects,
        )

    # -- reading back ------------------------------------------------------

    def read_entries(self):
        return self._existing()

    # -- the two that refuse ----------------------------------------------

    def update(self, *args, **kwargs):
        raise AppendOnlyError(
            "ledger entries are never mutated (GB_INTERFACES.md shape 5, "
            "append-only). A correction is a NEW entry referencing the id of the "
            "entry it corrects — see append_correction()"
        )

    def delete(self, *args, **kwargs):
        raise AppendOnlyError(
            "ledger entries are never deleted (GB_INTERFACES.md shape 5, "
            "append-only). The wrong record stays; append a correction instead"
        )

    # -- internals ---------------------------------------------------------

    def _existing(self):
        if not self.path.exists():
            return []
        return load(self.path)

    def _append(self, entry):
        entries = self._existing()
        _require_unique(entries, entry["id"])
        line = serialize(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return entry


def _build(**fields):
    """Validate and normalise one entry. Every field is stated, null where empty."""
    entry = {field: fields[field] for field in ENTRY_FIELDS}

    if not entry["id"] or not isinstance(entry["id"], str):
        raise ValueError("id must be a non-empty string")
    if entry["status"] not in STATUSES:
        raise ValueError(
            f"status {entry['status']!r} is outside the shape 5 vocabulary "
            f"({'|'.join(STATUSES)}); adding a value is a seam change"
        )
    if entry["mode"] not in ("approve", "autopilot"):
        raise ValueError(f"mode must be 'approve' or 'autopilot', got {entry['mode']!r}")

    for field in ("config_version", "code_version"):
        if not entry[field] or not isinstance(entry[field], str):
            raise ValueError(f"{field} must be a non-empty string")

    # prompt_version is null when no LLM produced the proposal. A placeholder
    # string would claim there was a prompt and lose which one.
    prompt_version = entry["prompt_version"]
    if prompt_version is not None and (
        not isinstance(prompt_version, str)
        or prompt_version.strip().lower() in ("", "none", "n/a", "null")
    ):
        raise ValueError(
            f"prompt_version must be a real version string or null, got "
            f"{prompt_version!r} — null means no LLM produced this proposal"
        )

    # Both null in autopilot, which is a recorded fact and not a gap.
    if entry["mode"] == "autopilot" and (
        entry["approved_by"] is not None or entry["approved_at"] is not None
    ):
        raise ValueError(
            "approved_by and approved_at are null in autopilot mode: no human "
            "confirmed, and the ledger must not be able to claim otherwise"
        )
    if (entry["approved_at"] is None) != (entry["approved_by"] is None):
        raise ValueError("approved_by and approved_at are set together or not at all")

    for field in ("ts", "as_of"):
        entry[field] = iso_utc(entry[field])
    if entry["approved_at"] is not None:
        entry["approved_at"] = iso_utc(entry["approved_at"])

    return entry


def _require_root(entries, root_id):
    for entry in entries:
        if entry["id"] == root_id:
            if entry["root_id"] is not None:
                raise ValueError(
                    f"root_id {root_id!r} points at a follow-up, not a root; chains "
                    f"fold on the ROOT id and a forked chain hides a position"
                )
            return entry
    raise ValueError(
        f"no root entry {root_id!r} in this ledger — the root is written before "
        f"submission (5a), so it always exists first"
    )


def _require_entry(entries, entry_id):
    if not any(entry["id"] == entry_id for entry in entries):
        raise ValueError(f"cannot correct {entry_id!r}: no such entry in this ledger")


def _require_unique(entries, entry_id):
    if any(entry["id"] == entry_id for entry in entries):
        raise ValueError(f"duplicate entry id {entry_id!r}: a chain must be unambiguous")


# ---------------------------------------------------------------------------
# The reader — folds chains the way the dashboard must
# ---------------------------------------------------------------------------

def list_roots(entries):
    """The decision entries, in append order. One per position."""
    return [entry for entry in entries if entry["root_id"] is None]


def fold_chain(entries, root_id):
    """One position's whole history, in append order.

    Folded by `root_id`, never by adjacency: in any real run the entries of
    different chains interleave, and a fold that walks forward from a root until
    it meets another root is wrong about most of them.
    """
    chain = [e for e in entries if (e["root_id"] or e["id"]) == root_id]
    if not chain or chain[0]["id"] != root_id or chain[0]["root_id"] is not None:
        raise KeyError(f"no root entry {root_id!r} in these entries")
    status = chain[-1]["status"]
    return {
        "root_id": root_id,
        "entries": chain,
        "status": status,
        "terminal": is_terminal(status),
    }


def current_status(entries, root_id):
    """(status, terminal) for a chain — the latest entry wins."""
    chain = fold_chain(entries, root_id)
    return chain["status"], chain["terminal"]


def is_terminal(status):
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return status in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# client_order_id — shape 4's id scheme
# ---------------------------------------------------------------------------

def client_order_id(root_id, env=None):
    """``<ORDER_ID_PREFIX><root entry id>``, prefix read from the environment.

    The prefix is **configuration, never a constant** (CLAUDE.md, shape 4): each
    box sets its own in `.env`, the two boxes share an account, and a default
    baked into this file would put one pod's prefix on the other pod's orders.
    The example values live in `.env.example` and the seam, clearly marked as
    examples; no literal appears here. An unset prefix raises rather than guessing.

    Embedding the ROOT entry id is what gives idempotency at the broker: a
    retried submission after a timeout carries the same `client_order_id` and
    Alpaca refuses the duplicate instead of opening a second position.
    """
    environment = os.environ if env is None else env
    prefix = environment.get(_ORDER_ID_PREFIX_ENV)
    if not prefix:
        raise ValueError(
            f"{_ORDER_ID_PREFIX_ENV} is not set in this environment. It is "
            f"per-box configuration and is never hardcoded; set it in .env "
            f"rather than defaulting it here"
        )
    if not root_id or not isinstance(root_id, str):
        raise ValueError("root_id must be a non-empty string")
    return prefix + root_id


# ---------------------------------------------------------------------------
# Replay — the provenance claim, executable
# ---------------------------------------------------------------------------

def replay_root(entry, thresholds, config_version=None):
    """Re-derive a root entry's verdict from the entry's own embedded inputs.

    Nothing outside the entry is consulted except the config it names. If the
    re-derived verdict is identical, the decision is reproducible; if it is not,
    either the record was edited or the code changed, and both are findings.

    Returns ``{"matched", "verdict", "differences"}``. See
    :func:`assert_replays` for the form that raises.
    """
    from glassbox import governor

    if entry.get("root_id") is not None:
        raise ValueError(
            "only a root entry carries a decision to replay; a follow-up records a "
            "transition, not a verdict"
        )
    if config_version is not None and config_version != entry["config_version"]:
        raise ValueError(
            f"refusing to replay under a different config: entry was decided under "
            f"{entry['config_version']}, you passed {config_version}. Reproducing a "
            f"verdict under other thresholds is not a reproduction"
        )

    snapshot = entry.get("snapshot") or {}
    for key in ("account_state", "clock"):
        if key not in snapshot:
            raise ValueError(
                f"snapshot has no {key!r}: this entry cannot be replayed, which "
                f"means its provenance claim cannot be checked"
            )

    verdict = governor.govern(
        entry["proposal"],
        snapshot["account_state"],
        snapshot["clock"],
        thresholds=thresholds,
        mode=entry["mode"],
        config_version=entry["config_version"],
    )
    differences = _diff(entry["verdict"], verdict)
    return {"matched": not differences, "verdict": verdict, "differences": differences}


def assert_replays(entry, thresholds, config_version=None):
    """Replay, and raise :class:`ReplayMismatch` if the record does not hold up."""
    result = replay_root(entry, thresholds, config_version=config_version)
    if not result["matched"]:
        raise ReplayMismatch(
            f"entry {entry['id']} does not replay: "
            + "; ".join(result["differences"])
        )
    return result["verdict"]


def _diff(recorded, replayed, path="verdict"):
    """Every way the two verdicts differ, named well enough to act on."""
    if isinstance(recorded, dict) and isinstance(replayed, dict):
        differences = []
        for key in sorted(set(recorded) | set(replayed)):
            if key not in recorded:
                differences.append(f"{path}.{key} missing from the recorded verdict")
            elif key not in replayed:
                differences.append(f"{path}.{key} not produced on replay")
            else:
                differences += _diff(recorded[key], replayed[key], f"{path}.{key}")
        return differences
    if isinstance(recorded, list) and isinstance(replayed, list):
        if len(recorded) != len(replayed):
            return [f"{path}: {len(recorded)} recorded vs {len(replayed)} on replay"]
        differences = []
        for index, (left, right) in enumerate(zip(recorded, replayed)):
            differences += _diff(left, right, f"{path}[{index}]")
        return differences
    if recorded != replayed:
        return [f"{path}: recorded {recorded!r} vs replayed {replayed!r}"]
    return []
