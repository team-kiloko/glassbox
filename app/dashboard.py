"""GlassBox audit dashboard — a read-only Streamlit view of a provenance ledger.

Run it with ``streamlit run app/dashboard.py`` from the repo root (app/README.md).

Everything the page shows is derived from a ledger JSONL file through the
ledger's OWN helpers — ``glassbox.ledger.load / list_roots / fold_chain /
current_status`` — and nothing else. The dashboard never folds a chain by
adjacency and never treats ``partial_fill`` as an end state, because the ledger
module already knows both rules and a second copy of either would be a second
thing to get wrong (demo/README.md).

The module is split in two halves on purpose:

* **Pure functions** (everything above ``main``): take entries or a root entry,
  return plain dicts and lists, touch no UI and no network. These are what
  ``tests/test_dashboard_contract.py`` (GB-X) exercises against the two
  committed demo ledgers.
* **The Streamlit page** (``main`` and its helpers): imports ``streamlit``
  lazily so the pure half can be imported and tested without a UI runtime.

Three views:

1. **Roots** — one row per root entry: id, folded status, structure, underlying,
   qty, the strategist's ``claimed_max_loss`` beside the governor's
   ``computed_max_loss``, and the three provenance versions.
2. **Chain** — one root's whole history in append order, plus the verdict's
   ``checks[]`` rendered generically. A check is ``{rule, passed, detail}`` and
   the seam (GB_INTERFACES.md 3a) pins seven core names; any ``x_`` rule, and any
   name the seam has never heard of, renders exactly the same way.
3. **Hero** — the paired roots each run writes: one approved and one
   ``governor_rejected`` under the same ``config_version`` and the same ``as_of``
   second, side by side. The rejected one's ``computed_max_loss`` vs ``cap``
   sits next to its ``claimed_max_loss`` and ``claim_divergence``, every number
   parsed out of ``verdict.reason`` — the governor's own words, not a figure the
   dashboard computed.

Replay (``replay_root``) is read-only: it re-runs the governor on the entry's own
embedded inputs under the config file whose content hash the entry names, and
reports ``matched``. If no file in the repo hashes to that ``config_version`` the
button says so rather than replaying under something else.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    # `streamlit run app/dashboard.py` puts app/ on sys.path, not the repo root.
    sys.path.insert(0, str(REPO_ROOT))

from glassbox.ledger import (  # noqa: E402  (path fix above is deliberate)
    current_status,
    fold_chain,
    list_roots,
    load,
    replay_root,
)

__all__ = [
    "DEFAULT_LEDGER", "LEDGER_CHOICES", "CORE_RULES", "CONFIG_SEARCH_DIRS",
    "parse_detail", "root_rows", "render_checks", "chain_timeline",
    "find_pairs", "hero_numbers", "resolve_thresholds_path", "replay",
]

#: The competition sample is the default because its pairs are the scored run's.
DEFAULT_LEDGER = "demo/ledger_competition_sample.jsonl"
LEDGER_CHOICES = (
    "demo/ledger_competition_sample.jsonl",
    "demo/ledger_sample.jsonl",
)

#: GB_INTERFACES.md 3a — the pinned core `checks[]` vocabulary. Anything else
#: is either an `x_` extension or a name this dashboard has never seen, and
#: both render generically; the set exists only to LABEL a row, never to gate it.
CORE_RULES = (
    "structure_valid", "net_reconciles", "max_loss_cap", "coverage",
    "cash_floor", "churn_guard", "market_open",
)

#: Where a `config_version` content hash is looked for. `config/` holds the
#: live profiles; the governor fixtures directory holds the PROPOSED thresholds
#: the oldest dev-ledger decisions were made under.
CONFIG_SEARCH_DIRS = ("config", "tests/fixtures/governor")

_KV = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[^\s]+)")


# ---------------------------------------------------------------------------
# Pure functions — no UI, no network, no clock
# ---------------------------------------------------------------------------

def parse_detail(text):
    """``key=value`` tokens from a check `detail` or a verdict `reason`.

    The governor writes every number a decision turned on as ``name=value``
    inside free text. This pulls them out without knowing the names in advance,
    so a rule this dashboard has never heard of still yields its numbers.
    Numeric values become floats; ``null`` becomes None; everything else stays a
    string. A key repeated in the text keeps its FIRST value — in a rejection
    `reason` the first occurrence is the failing check's own detail.
    """
    found = {}
    for match in _KV.finditer(text or ""):
        key = match.group("key")
        if key in found:
            continue
        found[key] = _coerce(match.group("value").rstrip(",;"))
    return found


def _coerce(raw):
    if raw == "null":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return float(raw)
    except ValueError:
        return raw


def _approved(root):
    verdict = root.get("verdict") or {}
    return bool(verdict.get("approved"))


def _as_of_second(root):
    """The id's clock prefix — ``20260902T150903Z`` — which is the run's second."""
    return root["id"].split("-", 1)[0]


def _computed_max_loss(root):
    """The governor's own figure, read from the ``max_loss_cap`` check detail."""
    for check in (root.get("verdict") or {}).get("checks") or []:
        if check.get("rule") == "max_loss_cap":
            return parse_detail(check.get("detail")).get("computed_max_loss")
    return None


def root_rows(entries):
    """One row per root, in append order — view (a).

    Status is the FOLDED status (``current_status``), never the root's own:
    a root is written as ``approved_pending`` and its chain may since have
    filled, expired or been canceled.
    """
    rows = []
    for root in list_roots(entries):
        status, terminal = current_status(entries, root["id"])
        proposal = root.get("proposal") or {}
        rows.append({
            "id": root["id"],
            "status": status,
            "terminal": terminal,
            "approved": _approved(root),
            "structure": proposal.get("structure"),
            "underlying": proposal.get("underlying"),
            "qty": proposal.get("qty"),
            "claimed_max_loss": proposal.get("claimed_max_loss"),
            "computed_max_loss": _computed_max_loss(root),
            "config_version": root.get("config_version"),
            "code_version": root.get("code_version"),
            "prompt_version": root.get("prompt_version"),
            "mode": root.get("mode"),
            "as_of": root.get("as_of"),
            "ts": root.get("ts"),
        })
    return rows


def render_checks(verdict):
    """``checks[]`` as uniform rows — core, ``x_`` and unknown alike.

    Each check is ``{rule, passed, detail}`` and that is all this function
    relies on. ``kind`` is a label: ``core`` for a seam-pinned name, ``x`` for
    the governor lead's extension point, ``unknown`` for anything else — and an
    unknown rule renders with the same columns, because a dashboard that
    dropped a check it did not recognise would be hiding a decision.
    """
    rows = []
    for check in (verdict or {}).get("checks") or []:
        rule = check.get("rule")
        if rule in CORE_RULES:
            kind = "core"
        elif isinstance(rule, str) and rule.startswith("x_"):
            kind = "x"
        else:
            kind = "unknown"
        rows.append({
            "rule": rule if rule is not None else "(unnamed)",
            "passed": bool(check.get("passed")),
            "kind": kind,
            "detail": check.get("detail") or "",
            "numbers": parse_detail(check.get("detail")),
        })
    return rows


def chain_timeline(entries, root_id):
    """One position's history, folded by ``root_id`` through the ledger helper.

    Every step carries what a reader needs to see the order move: the entry's
    own ``ts`` and ``status``, the broker order id and status if an order
    exists, the fill if one exists, and ``corrects`` if the entry is a
    correction. ``terminal`` on the chain is the ledger's answer, so a chain
    resting on ``partial_fill`` shows as still open.
    """
    chain = fold_chain(entries, root_id)
    steps = []
    for entry in chain["entries"]:
        order = entry.get("order") or {}
        fill = entry.get("fill") or {}
        steps.append({
            "id": entry["id"],
            "ts": entry["ts"],
            "status": entry["status"],
            "is_root": entry["root_id"] is None,
            "corrects": entry.get("corrects"),
            "order_id": order.get("order_id"),
            "client_order_id": order.get("client_order_id"),
            "order_status": order.get("status"),
            "net_limit_price": order.get("net_limit_price"),
            "filled_qty": fill.get("filled_qty"),
            "filled_avg_price": fill.get("filled_avg_price"),
            "filled_at": fill.get("filled_at"),
        })
    return {
        "root_id": root_id,
        "status": chain["status"],
        "terminal": chain["terminal"],
        "steps": steps,
    }


def find_pairs(entries):
    """The hero pairs — view (c).

    A run writes one approved root and one deliberately-bad ``governor_rejected``
    root under the SAME ``config_version`` and the SAME ``as_of`` second (the id
    prefix). Pairing on both is what makes the comparison honest: same numbers,
    same clock, same account state, two different proposals, two different
    answers. Roots with no partner are not pairs and are not returned.
    """
    by_key = {}
    for root in list_roots(entries):
        key = (root.get("config_version"), _as_of_second(root))
        by_key.setdefault(key, []).append(root)

    pairs = []
    for (config_version, second), group in by_key.items():
        approved = [r for r in group if _approved(r)]
        rejected = [r for r in group if r["status"] == "governor_rejected"]
        if not approved or not rejected:
            continue
        for winner, loser in zip(approved, rejected):
            pairs.append({
                "config_version": config_version,
                "as_of_second": second,
                "as_of": winner.get("as_of"),
                "approved": winner,
                "rejected": loser,
                "approved_status": current_status(entries, winner["id"])[0],
                "rejected_numbers": hero_numbers(loser),
                "approved_numbers": hero_numbers(winner),
            })
    pairs.sort(key=lambda pair: pair["as_of_second"])
    return pairs


def hero_numbers(root):
    """The four figures the demo's argument rests on, from ``verdict.reason``.

    ``computed_max_loss`` and ``cap`` are the governor's arithmetic;
    ``claimed_max_loss`` is what the proposal said; ``claim_divergence`` is the
    difference the governor wrote down. They are read from the verdict's
    ``reason`` text — the governor's own sentence — and NOT recomputed here, so
    the dashboard cannot tell a story the ledger does not.
    """
    verdict = root.get("verdict") or {}
    numbers = parse_detail(verdict.get("reason"))
    # An APPROVED reason carries no figures ("all 10 checks passed"), so the
    # twin's numbers come from its max_loss_cap check detail — still the
    # governor's own sentence, still not recomputed here.
    for check in verdict.get("checks") or []:
        if check.get("rule") == "max_loss_cap":
            for key, value in parse_detail(check.get("detail")).items():
                numbers.setdefault(key, value)
    return {
        "computed_max_loss": numbers.get("computed_max_loss"),
        "cap": numbers.get("cap"),
        "claimed_max_loss": numbers.get("claimed_max_loss"),
        "claim_divergence": numbers.get("claim_divergence"),
        "approved": bool(verdict.get("approved")),
        "reason": verdict.get("reason"),
        "failed_rules": [
            check.get("rule") for check in verdict.get("checks") or []
            if not check.get("passed")
        ],
    }


def resolve_thresholds_path(config_version, search_dirs=CONFIG_SEARCH_DIRS,
                            root=REPO_ROOT):
    """The config file whose content hash IS ``config_version``, or None.

    A ``config_version`` is ``sha256:<hex>`` of the thresholds file's bytes
    (GB_INTERFACES.md shape 3). The dashboard hashes every ``*.json`` under the
    search dirs and returns the one that matches — by content, never by name,
    so a renamed file still resolves and an edited one correctly does not.
    """
    if not isinstance(config_version, str) or not config_version.startswith("sha256:"):
        return None
    wanted = config_version.split(":", 1)[1]
    for directory in search_dirs:
        for path in sorted((Path(root) / directory).glob("*.json")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest == wanted:
                return path
    return None


def replay(root, search_dirs=CONFIG_SEARCH_DIRS, repo_root=REPO_ROOT):
    """Replay one root under the config it names. Read-only; no network.

    Returns ``{replayable, matched, differences, thresholds_path, error}``.
    ``replayable`` is False — with ``error`` saying why — when no file hashes to
    the entry's ``config_version`` or the entry has no decision to replay. It is
    never True on a guess: replaying under a different config is not a
    reproduction, and ``replay_root`` itself refuses that.
    """
    path = resolve_thresholds_path(root.get("config_version"), search_dirs, repo_root)
    if path is None:
        return {
            "replayable": False, "matched": None, "differences": [],
            "thresholds_path": None,
            "error": (
                f"no file under {', '.join(search_dirs)} hashes to "
                f"{root.get('config_version')}; the thresholds this decision was "
                f"made under are not in the repo at this commit"
            ),
        }
    thresholds = json.loads(path.read_text(encoding="utf-8"))
    try:
        result = replay_root(root, thresholds, config_version=root["config_version"])
    except (ValueError, KeyError) as exc:
        return {
            "replayable": False, "matched": None, "differences": [],
            "thresholds_path": path.relative_to(repo_root).as_posix(), "error": str(exc),
        }
    return {
        "replayable": True,
        "matched": result["matched"],
        "differences": list(result["differences"]),
        "thresholds_path": path.relative_to(repo_root).as_posix(),
        "error": None,
    }


# ---------------------------------------------------------------------------
# The Streamlit page
# ---------------------------------------------------------------------------

def _money(value):
    return "—" if value is None else f"{value:,.2f}"


def _short(text, keep=18):
    if not text:
        return "—"
    return text if len(text) <= keep else text[:keep] + "…"


def main():
    import streamlit as st

    st.set_page_config(page_title="GlassBox audit", page_icon="🔍", layout="wide")
    st.title("GlassBox — provenance ledger audit")
    st.caption(
        "Read-only. Every row is folded by root id through the ledger's own "
        "helpers; every number is the governor's, read back from the record."
    )

    with st.sidebar:
        st.header("Ledger")
        choice = st.selectbox("Committed sample", LEDGER_CHOICES, index=0)
        custom = st.text_input("…or a path relative to the repo root", value="")
        ledger_path = Path(REPO_ROOT) / (custom.strip() or choice)
        st.caption(f"Reading `{ledger_path.relative_to(REPO_ROOT).as_posix()}`")

    if not ledger_path.exists():
        st.error(f"No ledger at {ledger_path}")
        return

    entries = load(ledger_path)
    rows = root_rows(entries)
    pairs = find_pairs(entries)

    st.sidebar.metric("Entries", len(entries))
    st.sidebar.metric("Roots", len(rows))
    st.sidebar.metric("Open chains", sum(1 for r in rows if not r["terminal"]))

    hero_tab, roots_tab, chain_tab = st.tabs(["Hero: the pair", "Roots", "Chain"])

    with hero_tab:
        _hero_view(st, pairs)
    with roots_tab:
        _roots_view(st, rows)
    with chain_tab:
        _chain_view(st, entries, rows)


def _hero_view(st, pairs):
    st.subheader("Same config, same second, same account state — two answers")
    st.markdown(
        "Each run wrote one approved root and one **deliberately bad** root. "
        "The governor recomputed max loss for both from strikes, quantity and "
        "net price. It read the proposal's `claimed_max_loss` only to write "
        "down how far off it was."
    )
    if not pairs:
        st.info("No approved / governor_rejected pair shares a config_version and as_of second in this ledger.")
        return

    labels = [f"{p['as_of_second']}  ·  {p['approved']['id']}  vs  {p['rejected']['id']}" for p in pairs]
    picked = st.selectbox("Pair", range(len(pairs)), format_func=lambda i: labels[i])
    pair = pairs[picked]

    left, right = st.columns(2)
    for column, side, root, numbers, title in (
        (left, "approved", pair["approved"], pair["approved_numbers"], "APPROVED"),
        (right, "rejected", pair["rejected"], pair["rejected_numbers"], "GOVERNOR REJECTED"),
    ):
        with column:
            (st.success if side == "approved" else st.error)(title)
            proposal = root.get("proposal") or {}
            st.code(root["id"], language=None)
            st.write(
                f"**{proposal.get('structure')}** · {proposal.get('underlying')} · "
                f"qty {proposal.get('qty')} · "
                + ", ".join(
                    f"{leg.get('action')} {leg.get('symbol')} @ {leg.get('limit_price')}"
                    for leg in proposal.get("legs") or []
                )
            )
            a, b = st.columns(2)
            a.metric("computed_max_loss (governor)", _money(numbers["computed_max_loss"]))
            b.metric("cap", _money(numbers["cap"]))
            c, d = st.columns(2)
            c.metric("claimed_max_loss (proposal)", _money(numbers["claimed_max_loss"]))
            d.metric("claim_divergence", _money(numbers["claim_divergence"]))
            if numbers["failed_rules"]:
                st.write("Failed on: " + ", ".join(f"`{r}`" for r in numbers["failed_rules"]))
            st.caption(numbers["reason"])
            _replay_button(st, root, key=f"hero-{side}-{root['id']}")

    st.divider()
    st.caption(
        f"config_version `{pair['config_version']}` · as_of `{pair['as_of']}` · "
        f"approved chain is now `{pair['approved_status']}`"
    )


def _roots_view(st, rows):
    st.subheader("One row per root, folded by root id")
    table = [{
        "id": r["id"],
        "status": r["status"],
        "terminal": r["terminal"],
        "structure": r["structure"],
        "underlying": r["underlying"],
        "qty": r["qty"],
        "claimed_max_loss": r["claimed_max_loss"],
        "computed_max_loss": r["computed_max_loss"],
        "config_version": _short(r["config_version"]),
        "code_version": _short(r["code_version"], 12),
        "prompt_version": r["prompt_version"] if r["prompt_version"] is not None else "null (no LLM)",
        "mode": r["mode"],
    } for r in rows]
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(
        "`prompt_version` is null when no language model produced the proposal; "
        "that is a recorded fact, not a gap. `partial_fill` is not terminal."
    )


def _chain_view(st, entries, rows):
    st.subheader("A root's whole history, and the verdict that started it")
    ids = [r["id"] for r in rows]
    if not ids:
        st.info("No roots in this ledger.")
        return
    root_id = st.selectbox("Root", ids, format_func=lambda i: f"{i}  ({next(r['status'] for r in rows if r['id'] == i)})")
    timeline = chain_timeline(entries, root_id)
    root = next(e for e in entries if e["id"] == root_id)

    st.markdown(f"**Status:** `{timeline['status']}` · terminal: `{timeline['terminal']}`")
    st.markdown("**Timeline**")
    st.dataframe([{
        "ts": s["ts"], "status": s["status"], "entry": s["id"],
        "order_id": s["order_id"], "order_status": s["order_status"],
        "net_limit": s["net_limit_price"], "filled_qty": s["filled_qty"],
        "filled_avg": s["filled_avg_price"], "corrects": s["corrects"],
    } for s in timeline["steps"]], use_container_width=True, hide_index=True)

    verdict = root.get("verdict") or {}
    st.markdown(
        f"**Verdict:** {'approved' if verdict.get('approved') else 'rejected'} · "
        f"mode `{verdict.get('mode')}` · config `{_short(verdict.get('config_version'))}`"
    )
    st.caption(verdict.get("reason"))

    st.markdown("**checks[]** — core names from the seam, `x_` extensions and anything else, rendered alike")
    for check in render_checks(verdict):
        icon = "✅" if check["passed"] else "❌"
        tag = {"core": "core", "x": "x_ extension", "unknown": "unknown rule"}[check["kind"]]
        with st.expander(f"{icon} `{check['rule']}`  ·  {tag}", expanded=not check["passed"]):
            st.write(check["detail"])
            if check["numbers"]:
                st.json(check["numbers"], expanded=False)

    _replay_button(st, root, key=f"chain-{root_id}")

    with st.expander("Proposal (as recorded)"):
        st.json(root.get("proposal"))
    with st.expander("Snapshot (account state and clock the decision was made on)"):
        st.json(root.get("snapshot"))


def _replay_button(st, root, key):
    if st.button("Replay this decision", key=key):
        result = replay(root)
        if not result["replayable"]:
            st.warning(f"Not replayable: {result['error']}")
            return
        if result["matched"]:
            st.success(f"matched = True — re-derived under `{result['thresholds_path']}` from the entry's own inputs")
        else:
            st.error(f"matched = False under `{result['thresholds_path']}`")
            for difference in result["differences"]:
                st.write(f"- {difference}")


if __name__ == "__main__":
    main()
