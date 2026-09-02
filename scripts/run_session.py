#!/usr/bin/env python3
"""The session loop: run_cycle, on an interval, until the stop time.

Autopilot. This is the program that trades the scored session, and it is
deliberately the least clever file in the repository — it holds no risk opinion,
no market opinion and no arithmetic. It calls :func:`run_cycle.run_cycle`, prints
one line, sleeps, and repeats. Every number that could refuse a trade belongs to
the governor; every number that paces the loop lives in
`config/runner.PROPOSED.json`.

What a loop adds to a one-shot run is not capability — `scripts/dry_run.py` can
already do everything a cycle does — it is **failure modes that only exist over
time**, and this file is mostly the four answers to them:

  * **It ends when it says it will.** `--stop` is required and has no default. On
    Thursday it is set before the close so anything the last cycle submits has
    time to fill inside the scored window.
  * **It can be suspended without being killed.** `touch PAUSE` suspends cycles
    at the next tick; `rm PAUSE` resumes them. A file, because a file needs no
    signal, no pid, no terminal and no second process — it works from any shell,
    including one on a phone. A paused session keeps ticking and keeps LOGGING,
    so silence never means "paused": silence means something is wrong.
  * **It stops rather than grinding.** Two CONSECUTIVE raised cycles halt the
    run. One is a transient — a venue hiccup, a page that did not come back —
    and a successful cycle resets the count. An unattended process that keeps
    retrying into a fault spends the afternoon doing nothing while looking busy,
    and on Thursday that is the whole session.
  * **A wrong account halts at once.** An `AccountIdentityError` is not a
    transient in anybody's judgement, and the one thing an unattended loop must
    never do with it is try again in fifteen minutes.

**`--env` is required and never defaulted.** `scripts/dry_run.py` defaults to
`.env` (dev) so reaching the scored account is always something a human typed.
A loop cannot borrow that reasoning: a default of any kind means a session that
ran for six hours against whichever account the default happened to name.

Usage:
    python scripts/run_session.py --env .env --stop 15:45 --cycles 2 --interval 60
    python scripts/run_session.py --env .env.competition --stop 19:45
    touch PAUSE     # suspend at the next tick
    rm PAUSE        # resume
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from glassbox.executor import AccountIdentityError  # noqa: E402

from run_cycle import (  # noqa: E402
    RUNNER_CONFIG,
    build_context,
    format_cycle_line,
    run_cycle,
)

import json  # noqa: E402

#: Exit codes, so a wrapper script or a human reading `echo $?` can tell the
#: three endings apart without parsing the log.
EXIT_OK = 0
EXIT_HALTED_ON_ERRORS = 3
EXIT_HALTED_ON_IDENTITY = 4

#: Failures that get no second chance. Everything else is worth one retry,
#: because most of it is the venue having a bad second.
_NEVER_RETRY = (AccountIdentityError,)


def _utc_now():
    return datetime.now(timezone.utc)


def run_session(context, *, stop_at, interval_seconds, pause_file,
                max_consecutive_errors, now=_utc_now, sleep=time.sleep,
                log=print, cycle=run_cycle, max_cycles=None):
    """Run cycles until the stop time, and return an exit code.

    Args:
        context: a :class:`run_cycle.RunContext`, passed straight through.
        stop_at: timezone-aware datetime. The loop runs no cycle at or after it.
        interval_seconds: how long to sleep between ticks.
        pause_file: a path; while it exists, cycles are suspended.
        max_consecutive_errors: how many raised cycles IN A ROW end the run.
        now / sleep: the clock and the wait, injected so GB-R can run a whole
            afternoon of ticks in milliseconds without a real one.
        log: called with one finished line at a time.
        cycle: the cycle function. Injected so the loop's own behaviour — pause,
            halt, stop — can be tested without a venue behind it.
        max_cycles: stop after this many cycles have RUN. For a bounded
            rehearsal; `None` means run to the stop time.

    Returns:
        `EXIT_OK`, `EXIT_HALTED_ON_ERRORS` or `EXIT_HALTED_ON_IDENTITY`.
    """
    pause_file = Path(pause_file)
    consecutive = 0
    ran = 0

    while True:
        moment = now()
        if moment >= stop_at:
            log(f"session=stop reason=stop_time at={_stamp(moment)} "
                f"stop_at={_stamp(stop_at)} cycles={ran}")
            return EXIT_OK

        if pause_file.exists():
            # Paused, not stopped. It keeps ticking and keeps saying so.
            log(f"session=paused at={_stamp(moment)} pause_file={pause_file} "
                f"— delete it to resume; cycles={ran}")
            sleep(interval_seconds)
            continue

        ran += 1
        cycle_id = f"{ran:04d}"
        try:
            result = cycle(context, cycle_id=cycle_id, now=moment)
        except _NEVER_RETRY as exc:
            log(f"cycle={cycle_id} ERROR {type(exc).__name__}: {exc}")
            log(f"session=HALT reason=account_identity cycle={cycle_id} — the "
                f"broker is not the account this run was authorised for. This is "
                f"not a transient and gets no retry. NOTHING further will be sent.")
            return EXIT_HALTED_ON_IDENTITY
        except Exception as exc:                    # noqa: BLE001 — see below
            # Broad on purpose: the loop's contract is that ANY raised cycle is
            # counted, not that it understands what went wrong. Narrowing this
            # would mean an unlisted exception killed the session on its first
            # occurrence, which is the behaviour the tolerance exists to avoid.
            consecutive += 1
            log(f"cycle={cycle_id} ERROR {type(exc).__name__}: {exc} "
                f"consecutive={consecutive}/{max_consecutive_errors}")
            if consecutive >= max_consecutive_errors:
                log(f"session=HALT reason=consecutive_errors "
                    f"count={consecutive} cycle={cycle_id} — two in a row is the "
                    f"system saying it cannot fix this by trying again. "
                    f"NOTHING further will be sent.")
                return EXIT_HALTED_ON_ERRORS
            sleep(interval_seconds)
            continue

        consecutive = 0
        log(format_cycle_line(result))

        if max_cycles is not None and ran >= max_cycles:
            log(f"session=stop reason=max_cycles cycles={ran} "
                f"at={_stamp(now())}")
            return EXIT_OK

        sleep(interval_seconds)


def _stamp(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_stop(value, reference):
    """`HH:MM` UTC on the session's own day, or a full ISO-8601 timestamp.

    `HH:MM` is what a human types at 09:25 on the morning of the run, and the
    day it means is the day the session starts. A full timestamp is accepted
    because a runbook that has to reason about midnight should be able to say so
    explicitly rather than trusting this to guess.
    """
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    else:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    parts = text.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise argparse.ArgumentTypeError(
            f"--stop takes HH:MM (UTC, on the session's own day) or a full "
            f"ISO-8601 timestamp, got {value!r}"
        )
    numbers = [int(p) for p in parts] + [0]
    return datetime.combine(
        reference.astimezone(timezone.utc).date(),
        clock_time(numbers[0], numbers[1], numbers[2]),
        tzinfo=timezone.utc,
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env", required=True, default=None, metavar="FILE",
        help="which env file to load, and therefore WHICH ACCOUNT this session "
             "trades. REQUIRED and never defaulted — a loop that ran for six "
             "hours against a defaulted account is the failure this prevents.",
    )
    parser.add_argument(
        "--stop", required=True, default=None, metavar="HH:MM|ISO",
        help="UTC time to stop at, on the session's own day. REQUIRED: a loop "
             "with a defaulted end is a loop that ends when someone remembers it.",
    )
    parser.add_argument(
        "--interval", type=int, default=None, metavar="SECONDS",
        help="seconds between cycles. Defaults to cycle_interval_seconds in "
             "config/runner.PROPOSED.json (PROPOSED 900).",
    )
    parser.add_argument(
        "--pause-file", default=None, metavar="PATH",
        help="while this file exists, cycles are suspended. Defaults to the "
             "pause_file in config/runner.PROPOSED.json.",
    )
    parser.add_argument(
        "--cycles", type=int, default=None, metavar="N",
        help="stop after N cycles have run, for a bounded rehearsal. Without it "
             "the session runs to --stop.",
    )
    parser.add_argument(
        "--no-submit", dest="submit", action="store_false",
        help="decide, govern and record every cycle, but send nothing to the "
             "broker. A rehearsal that still writes real ledger roots.",
    )
    parser.add_argument(
        "--mode", default="autopilot", choices=("autopilot", "approve"),
        help="ledger mode recorded on every decision this session makes.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    started = _utc_now()
    stop_at = parse_stop(args.stop, started)

    runner = json.loads(RUNNER_CONFIG.read_text(encoding="utf-8"))
    interval = args.interval if args.interval is not None else runner["cycle_interval_seconds"]
    pause_file = Path(args.pause_file) if args.pause_file else REPO / runner["pause_file"]

    context = build_context(args.env, mode=args.mode, submit=args.submit)
    profile = context.profile

    print("=" * 78)
    print("GlassBox SESSION — governed cycles until the stop time")
    print(f"profile          : {profile['name'].upper()}  env={profile['env_file']}  "
          f"account={profile['account_number']}  "
          f"scored={'YES' if profile['scored'] else 'no'}")
    if profile["scored"]:
        print("*** THIS IS THE SCORED COMPETITION ACCOUNT. Every order this session")
        print("*** places goes through the governor, in autopilot, and is recorded.")
    print(f"started          : {_stamp(started)}")
    print(f"stop_at          : {_stamp(stop_at)}")
    print(f"interval         : {interval}s"
          + (f"   cycles={args.cycles}" if args.cycles else ""))
    print(f"pause file       : {pause_file}   (touch to suspend, rm to resume)")
    print(f"submit           : {'YES — real orders' if context.submit else 'no'}")
    print(f"ledger           : {profile['ledger']}")
    print(f"governor config  : {profile['governor_thresholds'].name}")
    print(f"config_version   : {context.config_version}")
    print(f"code_version     : {context.code_version}")
    print("=" * 78)

    code = run_session(
        context, stop_at=stop_at, interval_seconds=interval, pause_file=pause_file,
        max_consecutive_errors=runner["max_consecutive_errors"],
        max_cycles=args.cycles,
    )
    print("=" * 78)
    print(f"SESSION ENDED, exit={code}  "
          f"({'clean' if code == EXIT_OK else 'HALTED — read the last lines above'})")
    print("=" * 78)
    return code


if __name__ == "__main__":
    sys.exit(main())
