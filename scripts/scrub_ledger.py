#!/usr/bin/env python3
"""Rebuild a profile's committed demo sample from its real ledger, scrubbed.

The harness mirrors each entry into the demo sample as it writes it. This
rebuilds that sample from the source ledger in one pass and, by default, REFUSES
to write if the result is not byte-identical to what is already there — so the
incremental mirror is checked rather than trusted, and a demo artefact that has
drifted from the ledger it claims to sample is a failure rather than a surprise
someone notices in a demo.

Three things it does that a `cp` would not:

1. **Scrubs identity fields**, with a per-profile exception list. On the scored
   profile `account_number` is KEPT: the competition account id is a required
   submission disclosure, and a sample that scrubbed it could not prove which
   account traded. An account number identifies; it does not authorise.
2. **Runs the recorder's credential scan over the finished bytes** — the same
   check `scripts/record_fixtures.py` makes before a fixture reaches disk. If
   either live credential appears anywhere in the output, nothing is written.
3. **Re-serializes through the ledger's own canonical form**, so the sample is
   byte-stable and a diff on it means a content change rather than a whitespace one.

Usage:
    python scripts/scrub_ledger.py --env .env.competition
    python scripts/scrub_ledger.py --env .env --write   # accept a rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from glassbox import ledger as ledger_mod  # noqa: E402
from glassbox.datafeed import load_config, load_dotenv  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
from dry_run import DemoMirror, load_profile  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", metavar="FILE",
                        help="which profile's ledger and demo sample to work on")
    parser.add_argument("--write", action="store_true",
                        help="write the rebuilt sample even if it differs from the "
                             "file on disk. Without this, a difference is reported "
                             "and nothing is touched.")
    args = parser.parse_args()

    profile = load_profile(args.env)
    load_dotenv(REPO / profile["env_file"])
    config = load_config()
    secrets = (config["api_key"], config["secret_key"])

    source, target = profile["ledger"], profile["demo_sample"]
    if not source.exists():
        raise SystemExit(f"no ledger at {source.relative_to(REPO)} — nothing to scrub")

    entries = ledger_mod.Ledger(source).read_entries()
    keep = ("account_number",) if profile["scored"] else ()
    mirror = DemoMirror(target, secrets, keep=keep)

    lines, kept_values = [], set()
    for entry in entries:
        scrubbed, _ = mirror.scrub(entry)
        lines.append(ledger_mod.serialize(scrubbed))
        identity = (scrubbed.get("snapshot") or {}).get("account_identity") or {}
        if identity.get("account_number"):
            kept_values.add(identity["account_number"])
    rebuilt = "".join(line + "\n" for line in lines)

    # The recorder's scan, over the finished bytes rather than per entry: a
    # credential split across two entries is not a thing, but a scan that only
    # ever sees fragments is exactly how one gets missed.
    for secret in secrets:
        if secret and secret in rebuilt:
            raise SystemExit(
                "ABORT: a credential appears in the scrubbed output. Nothing was "
                "written. This is a bug in the pipeline, not something to work around."
            )
    json.loads(lines[0]) if lines else None      # it is still JSONL

    existing = target.read_text(encoding="utf-8") if target.exists() else None
    identical = existing == rebuilt

    print(f"profile          : {profile['name']}  (scored={profile['scored']})")
    print(f"source ledger    : {source.relative_to(REPO)}  {len(entries)} entries")
    print(f"demo sample      : {target.relative_to(REPO)}")
    print(f"fields dropped   : {mirror.dropped_total}")
    print(f"fields kept      : {', '.join(mirror.kept) or 'none'}")
    if kept_values:
        print(f"account disclosed: {', '.join(sorted(kept_values))} — required by the "
              f"submission")
    print(f"credential scan  : clean over {len(rebuilt):,} bytes")
    print(f"matches on disk  : {identical}")

    if identical:
        print("nothing to do: the incremental mirror and a full rebuild agree.")
        return 0
    if not args.write:
        print("DIFFERS from the file on disk and --write was not given; nothing "
              "written. Re-run with --write to accept the rebuild.")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rebuilt, encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)}  ({len(rebuilt):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
