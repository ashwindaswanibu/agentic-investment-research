# A reproducible workbench demonstration

The public-demo package shows two application workflows with explicitly invented
inputs. It gives a reviewer something concrete to inspect without a model account,
market subscription, Docker daemon or a copy of an operator's research database.

## Walkthrough

1. **Instrument comparison:** inspect retained delayed quote timestamps, compare
   cash, shares, a long call and a call spread under the same declared outcomes,
   and see the alternative with a missing ask remain unavailable. These are
   computed expiration scenarios, not trades or predicted returns.
2. **Forecast accountability:** inspect a probability, baseline and resolution
   rules registered before an actual short fixture window. An invented report
   resolves it; a correction changes the outcome and score while preserving the
   original resolution. Unresolved records and abstentions remain visible.

All TEST prices, events, reports and probabilities are synthetic. Calculations,
storage, source binding and correction checks run through the application's
existing workflows. There are no agent tasks, model calls, external market
requests, funded accounts, mandates or ledger events in this package. It cannot
demonstrate agent research quality, market usefulness or options execution.

## Build and inspect

From a checkout, install Python 3.12+ dependencies into a virtual environment:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
python examples/public_demo.py build --output artifacts/public-demo
python examples/public_demo.py serve --directory artifacts/public-demo --port 8011
```

In a second terminal, with Node 24:

```sh
cd web
npm ci
npm run build
RESEARCH_API_URL=http://127.0.0.1:8011 PORT=3001 npm start
```

Open [the guided entry page](http://127.0.0.1:3001/demo). The regular Research,
Library and Paper views remain available for inspection. Read-only enforcement
is in the API and database, not only disabled buttons.

The output directory must not already exist. Use a new directory for each build;
the command never replaces an existing research database. A build waits a few
seconds for the forecast window to close. Timestamps, UUIDs and database hashes
vary between builds, and pending forecasts eventually become due. Reproducible
means the same inspectable workflow, not identical bytes or frozen current time.

## Isolation and integrity

The builder uses explicit settings and ignores ambient `RESEARCHDESK_*` values
and `.env` files. It only creates the prescribed examples; there is no export
command accepting a source database or arbitrary private artifact directory.
The viewer disables model and market providers, uses lexical retrieval and
reports the code sandbox as unavailable without probing Docker.

The manifest records the database hash and artifact inventory. Startup rejects
changed or incomplete packages. Hashes detect changes against this manifest;
they are not a publisher signature or a general-purpose secret scanner. Build
from reviewed source and retain the matching application revision and lockfiles.

SQLite opens the completed package using a read-only immutable connection. Stop
the viewer before replacing a package; build into a new directory and restart
against that directory. SQLite skips change detection for immutable files, so
editing a database while it is served is unsupported.
See [SQLite's URI contract](https://www.sqlite.org/uri.html).

Public hosting additionally needs an HTTPS deployment with the frontend pointing
at this dedicated viewer. Keep the API behind the frontend/reverse proxy. Do not
attach an execution worker, expose the operator service, or substitute its
database. The local recipe does not provision hosting or claim a verified public
URL. Container deployment and remote CI remain separate qualification gates.

## Why this design

Reusing the operator database would expose every retained artifact, prompt and
tool result through the viewer. A general redaction/export system would need a
separate publication policy and adversarial review. The smaller useful approach
is to build only two declared synthetic examples from an empty database using
the existing workflows, then serve them read-only.

Configuration isolation includes environment variables, not just dotenv files:
Pydantic's `_env_file=None` only disables dotenv loading. See the
[settings source documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
Regression tests set conflicting environment values and credentials, deny network
access, reject modified packages and exercise API mutation rejection.
