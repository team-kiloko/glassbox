# GlassBox audit dashboard

A read-only Streamlit view of a provenance ledger (GB_INTERFACES.md shape 5).
It folds chains by root id through the ledger's own helpers, renders every
`checks[]` rule generically, and puts each run's approved / rejected pair side
by side with the governor's numbers next to the strategist's claim.

## Run it locally

From the repo root, with the pinned `requirements.txt` installed:

```bash
streamlit run app/dashboard.py
```

The sidebar selects a committed sample: `demo/ledger_competition_sample.jsonl`
(default, the scored account's runs) or `demo/ledger_sample.jsonl` (the dev
account). A path relative to the repo root can be typed instead, e.g. a local
`data/ledger_dev.jsonl`.

Nothing on the page reaches the network. "Replay this decision" re-runs the
governor on the entry's own embedded proposal, account state and clock, under
the config file whose **content hash** equals the entry's `config_version`, and
shows `matched`. If no file in `config/` or `tests/fixtures/governor/` hashes to
that version the button says so; it never replays under a different config.

## Tests

`tests/test_dashboard_contract.py` (GB-X) imports the module's pure functions
and holds them to both committed demo ledgers. The Streamlit page itself is not
tested.

```bash
.venv\Scripts\python.exe -m pytest -q tests/test_dashboard_contract.py
```

## Deploying to Streamlit Community Cloud

Community Cloud deploys straight from a GitHub repo. The steps, once the repo
is **public** (SUBMISSION.md row 8 — flip only after the secrets scan):

1. Sign in at https://share.streamlit.io with the Jhoosier GitHub account.
2. "New app" → repository `team-kiloko/glassbox`, branch `main`, main file
   path `app/dashboard.py`. Python version: 3.11 or later.
3. No secrets are needed. The app reads only committed files and never loads
   `.env`; leave the Secrets panel empty.
4. The resulting `*.streamlit.app` URL is the Application URL for SUBMISSION.md
   row 10.

Deploying from a private repo is possible through Streamlit's GitHub
authorisation if the URL is wanted before flip day, but the submission needs
the repo public anyway, so the plan of record is: flip, then deploy.
