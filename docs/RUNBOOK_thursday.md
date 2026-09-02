# RUNBOOK — Thursday 2026-09-03, the scored session

**For teakeycee's box.** The competition account `PA3424LCNZBS` is LIVE-SCORED and
its **total account equity at EOD Thursday 2026-09-03** is the judged number
(`EVENT_FACTS.md`, Alpaca FAQ, `[primary]` ✅). This is the sequence for the day.

Read it once end to end before 13:30 UTC. There is no step here that is safe to
improvise, and the two positions already on the account need **nothing done to
them** — they expire Thursday and resolve themselves.

| | |
|---|---|
| **Market open** | 09:30 ET = **13:30 UTC** |
| **Market close** | 16:00 ET = **20:00 UTC** |
| **Session stop** | **19:45 UTC** — fifteen minutes early, so anything the last cycle submits has time to fill inside the scored window |
| **Account** | `PA3424LCNZBS`, selected ONLY by `--env .env.competition` |
| **Ledger** | `data/ledger_competition.jsonl` (gitignored) → `demo/ledger_competition_sample.jsonl` (committed) |
| **Governor config** | `config/thresholds.competition.json` — **FROZEN for the event** |

---

## 0. The standing rule

**No manual orders on this account. No flatten. No experiments. No ad-hoc reads
that could become writes.** Every order goes through the harness, under the
governor, with `--env .env.competition` typed explicitly. `--env` has **no
default** in `run_session.py` or `run_cycle.py`, so there is no way to reach this
account by forgetting something.

The two open positions (short 5x `SPY260903P00763000` / long 5x
`SPY260903P00758000`, max loss 2,067.00 against a 10,000.00 book cap) expire
Thursday **by construction** and are frozen. Do not close them to tidy up.

---

## 1. Before the bell — load the keys (YOUR step, ~13:15 UTC)

The keys are yours to place and yours to remove. Nothing in this repo writes
`.env.competition`, and nothing in it may.

```bash
cd ~/dev/glassbox
# Put ALPACA_API_KEY / ALPACA_SECRET_KEY for PA3424LCNZBS into .env.competition,
# plus ALPACA_PAPER_TRADE=true, the two paper base URLs, and ORDER_ID_PREFIX=tkc-
chmod 600 .env.competition
ls -l .env.competition        # expect -rw------- and nothing else
git status --short            # expect NOTHING under .env* — it is gitignored
```

If `git status` shows `.env`, `.env.competition` or `data/`: **stop.** Do not
commit, do not continue, raise it.

---

## 2. Pre-flight (13:20–13:29 UTC) — four checks, all read-only

```bash
cd ~/dev/glassbox

# (a) the suites are green. If they are not, you do not start.
.venv/bin/python -m pytest -q

# (a2) the working tree is CLEAN. `code_version` is recorded on every decision
#      this session makes, and an uncommitted tree records it as `<sha>-dirty` —
#      a version nobody can check out and replay against.
git status --short        # expect no output at all

# (b) the scored config has not drifted. This hash is recorded as
#     `config_version` on every scored verdict; if it changes, every recorded
#     verdict stops naming the numbers it was made under.
.venv/bin/python -c "import hashlib,pathlib;print('sha256:'+hashlib.sha256(pathlib.Path('config/thresholds.competition.json').read_bytes()).hexdigest())"
# expect: sha256:0066384c0e492d71138d3c6968745279edad70464a1a605edd9f6b695d4c69c9

# (c) the broker agrees who we are — over the same connection an order would
#     use. Reads /v2/account and NOTHING else. Writes nothing, anywhere.
.venv/bin/python - <<'PY'
import sys; sys.path[:0] = ['.', 'scripts']
from glassbox.datafeed import load_config, load_dotenv
from glassbox.executor import AlpacaPyTransport
from dry_run import load_profile, confirm_account
profile = load_profile('.env.competition')
load_dotenv(profile['env_file'])
config = load_config()                       # the paper guard fires here
identity, equity, _ = confirm_account(AlpacaPyTransport(config), profile, config)
print(f"account={identity['account_number']} status={identity['broker_status']}")
print(f"url={identity['trading_base_url']}")
print(f"equity={equity:,.2f}")
PY
# expect: account=PA3424LCNZBS  status=ACTIVE  url contains 'paper'

# (d) the ledger is where you left it: every chain terminal or legitimately open.
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, '.')
from glassbox import ledger as L
entries = L.load('data/ledger_competition.jsonl')
for root in L.list_roots(entries):
    status, terminal = L.current_status(entries, root['id'])
    print(f"{root['id']}  {status:<18} terminal={terminal}")
PY
```

**If (a), (b) or (c) is not as expected, do not start the session.** A failing
suite, a moved config hash or a wrong account number are each, on their own, a
reason to spend the morning finding out why instead.

---

## 3. Start the session (13:30 UTC)

```bash
cd ~/dev/glassbox
.venv/bin/python scripts/run_session.py --env .env.competition --stop 19:45
```

That is the whole command. Defaults come from `config/runner.PROPOSED.json`:
**900s (15 min) between cycles**, halt after **2 consecutive** raised cycles,
pause file `PAUSE` in the repo root.

Leave it in the foreground in a terminal you can see. If you need it to survive a
disconnect, run it under `tmux`/`screen` — **not** with `&`, because you want to
be able to read the log and press Ctrl-C.

The header prints the account, the stop time, the interval, the pause file, and
the config and code versions every decision will be recorded under. **Read it.**
If the account number or `scored=YES` is not what you expect, Ctrl-C immediately;
nothing has been sent at that point.

---

## 4. Watching the log

One line per cycle, `key=value` columns.

```
cycle=0001 as_of=2026-09-03T13:30:04Z open=true screened=412/38 candidates=1 approved=1/1 root=20260903T133004Z-... order=<uuid> status=filled
cycle=0002 as_of=2026-09-03T13:45:05Z open=true screened=410/40 candidates=1 approved=0/1 root=20260903T134505Z-... rejected_on=churn_guard
cycle=0003 as_of=2026-09-03T14:00:05Z open=true screened=411/39 candidates=0 skipped=no_candidates
```

| Field | What it means |
|---|---|
| `cycle=` | this session's cycle counter. Not in the ledger; ids there are content-hashed |
| `as_of=` | the timestamp the whole decision was measured against (6c) |
| `open=` | the venue's own clock. `open=false` ⇒ `skipped=market_closed`, nothing fetched, nothing written |
| `screened=A/R` | contracts accepted / rejected by the screener, failing closed |
| `candidates=` | proposals built. `0` ⇒ nothing survived the liquidity window |
| `approved=n/m` | how the **governor** ruled. This is the only opinion that matters |
| `root=` | the ledger root id. `client_order_id` is `tkc-` + this |
| `order=` / `status=` | the broker order id, and where the chain got to |
| `rejected_on=` | the checks that refused it, by name |
| `screen_rejects=` | on a `candidates=0` cycle: the screener's biggest fail-closed reasons |
| `excluded=` | on a `candidates=0` cycle: which liquidity-window test excluded the pairs |

**A cycle that refuses is the system working.** A session that submits once and
refuses twenty times is a good session; each refusal is a `governor_rejected`
root on the ledger carrying the whole `checks[]`, with the numbers the decision
turned on. `rejected_on=churn_guard` after a fill is **expected** — a filled
position holds its underlying for `churn_window_seconds` (3600) and the minimum
hold (7200).

**Cycles that propose nothing are normal on this chain, and the dev rehearsal
found out how normal.** Two cycles a minute apart on 2026-09-02 gave:

```
cycle=0001 ... screened=0/692  candidates=0 skipped=no_candidates screen_rejects=stale_quote:692,null_greeks:557,missing_bid:239 excluded=none
cycle=0002 ... screened=20/672 candidates=0 skipped=no_candidates screen_rejects=null_greeks:550,stale_quote:520,missing_bid:239 excluded=short_delta_band:10,short_open_interest:7
```

The free **indicative** feed serves a 0/1-DTE SPY chain whose quote freshness
swings hard minute to minute: the first cycle saw no quote inside
`quote_max_age_seconds` (300) at all, the second saw twenty contracts and still
found no 5-wide pair whose short leg was both inside the delta band and deep
enough in open interest. **This is the screener and the liquidity window failing
closed, exactly as designed** — a contract that cannot be fully evaluated is
never proposed. It is also why the counts are on the line: `stale_quote:692` and
`short_delta_band:10` are different problems with different answers.

If the whole session reads like the first line, the chain is the problem and no
config change is going to fix it that afternoon. If it reads like the second,
the liquidity window is what is binding, and **widening it is a decision for
teakeycee with a reason attached** — in `config/thresholds.competition.json`,
which is otherwise FROZEN, and never mid-session while orders are being judged
under the hash it currently has.

**What is NOT expected:** `approved=` climbing all afternoon with no refusals, or
the same underlying filling twice inside an hour. If you see either, **PAUSE it**
(§5) and look at the last root's `checks[]` before anything else.

---

## 5. To suspend, without killing it

```bash
touch ~/dev/glassbox/PAUSE      # suspends at the next tick, within 15 minutes
rm ~/dev/glassbox/PAUSE         # resumes at the tick after that
```

A paused session **keeps ticking and keeps logging**:

```
session=paused at=2026-09-03T15:15:02Z pause_file=/home/x/dev/glassbox/PAUSE — delete it to resume; cycles=7
```

So silence never means "paused". **Silence means something is wrong** — check the
process is alive.

Pausing does not cancel anything already at the broker. An order submitted by the
cycle before the pause goes on living its own life; the next cycle after you
resume will see it on the book, because a filled chain is an open position.

---

## 6. Stop, and unload the keys (19:45 UTC)

The session stops itself at `--stop` and prints:

```
session=stop reason=stop_time at=2026-09-03T19:45:xxZ stop_at=2026-09-03T19:45:00Z cycles=N
SESSION ENDED, exit=0  (clean)
```

Then:

```bash
cd ~/dev/glassbox

# 1. What the day did, from the ledger rather than from the log.
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, '.')
from glassbox import ledger as L
entries = L.load('data/ledger_competition.jsonl')
for root in L.list_roots(entries):
    status, terminal = L.current_status(entries, root['id'])
    verdict = root['verdict']
    failed = [c['rule'] for c in verdict['checks'] if not c['passed']]
    print(f"{root['ts']}  {status:<18} approved={verdict['approved']} "
          f"{'refused_on=' + ','.join(failed) if failed else ''}")
PY

# 2. Rebuild the committed demo sample and check it against its source. This
#    REFUSES to write unless a full rebuild is byte-identical to the incremental
#    mirror, so the artefact is checked rather than trusted.
.venv/bin/python scripts/scrub_ledger.py --env .env.competition
#    (add --write only if it reports a difference you have understood)

# 3. UNLOAD THE KEYS. This is the step that ends the day.
shred -u .env.competition        # or: rm -P / rm, per what your box has
ls -l .env.competition           # expect: No such file or directory

# 4. Commit the artefacts. NEVER .env*, NEVER data/, NEVER CLAUDE.local.md.
git status --short                # read every line before staging anything
git add demo/ledger_competition_sample.jsonl
git commit && git push            # a HANDOFF block that is not pushed does not exist
```

The positions on the account are left as they are. They expire Thursday and
resolve into the scored equity; there is nothing to flatten and nothing to close.

---

## 7. If it halts

The session exits **non-zero** and says why on its last two lines. There are
exactly two ways it halts on its own.

### `exit=4` — `session=HALT reason=account_identity`

The broker answered `/v2/account` with an account that is **not**
`PA3424LCNZBS`, or could not answer at all. **Nothing was sent** — the guard runs
before the payload is built, on the connection the order would have used.

1. **Do not restart it.** This gets no retry by design.
2. Check `.env.competition` holds the **competition** key pair and not the dev
   one. The two accounts are indistinguishable in every other respect: same
   endpoint, same SDK, same payloads.
3. If the keys are right and the broker still disagrees, stop for the day and
   raise it. An order on the wrong account cannot be taken back.

### `exit=3` — `session=HALT reason=consecutive_errors`

Two cycles in a row raised. The line above it carries the exception type and its
message; that is the thing to read first.

1. Look at the ledger (§6 step 1). A cycle raises **after** writing its root only
   if the failure was at the broker; if the last root is `approved_pending` with
   no follow-up, an order may be in flight — check it at the broker before doing
   anything else.
2. Fix or wait out the cause. A venue 5xx or a timeout is usually the venue.
3. Restart with the SAME command. It is safe: a cycle re-run in the same second
   as one already on the ledger is recognised and decides nothing, and every
   `client_order_id` embeds its root id, so the broker refuses a duplicate rather
   than opening a second position.
4. If it halts twice for the same reason, `touch PAUSE`, and stop.

### Anything else

**Ctrl-C** is always safe between cycles: it ends the session and sends nothing.
An order already submitted is at the broker and unaffected — the chain will show
`submitted` with no terminal follow-up, which is honest, and the next session's
first cycle sees it as a risk-bearing position.

---

## 8. What NOT to do, all day

- Do **not** run `scripts/dry_run.py --submit` against `.env.competition`
  alongside the session. Two writers on one ledger is not a supported thing.
- Do **not** edit `config/thresholds.competition.json` or `config/profiles.json`.
  They are frozen for the event: a threshold change mid-event retroactively
  changes what every recorded verdict means.
- Do **not** edit any ledger file. It is append-only; a correction is a new entry
  (`append_correction`), never a change to an old one.
- Do **not** place a manual order, on any account, from any session.
- Do **not** leave the keys loaded past the stop. §6 step 3 is not optional.
