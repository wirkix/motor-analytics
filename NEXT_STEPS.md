# Wide-Table Motor Analytics — status & next steps

Project #2 of the portfolio roadmap (see the "Data Pipeline Roadmap"
Claude artifact, and [Job Market Radar](https://github.com/wirkix/job-market-radar)
for #1). This file is a snapshot of where the build stands and exactly
what's left — the durable docs are [README.md](README.md) (architecture,
setup, data model) and [CLAUDE.md](CLAUDE.md) (non-obvious "why"s and
footguns); this one is disposable once the three blockers below are
cleared and can be deleted.

## What's built (2026-08-23)

The full pipeline exists and is tested end to end against a bundled
synthetic fixture — no external dataset or API keys needed to build or
demo it right now:

- **`ingest/`** — Pandas cleaning (dedup, text normalization, numeric
  coercion) + manufacturer-stratified sampling of the raw Craigslist CSV.
- **`enrich/`** — Banxico SIE API client (FX fix rate `SF43718` + inflation
  index `SP1`), forward-filled to a daily calendar; falls back to a flagged
  constant when no token is set, so the pipeline never hard-fails on this.
- **`dbt/`** — the wide mart itself, `fct_used_car_listing`: ~65 columns
  (identity, age/mileage, USD price, Banxico-driven MXN price — nominal
  and inflation-adjusted, powertrain, body/condition, data-quality flags).
- **`app/`** — a Streamlit chat UI where Claude writes and runs SQL against
  the table live via a `run_sql` tool, instead of a fixed dashboard.
- **Tests** — 30 pytest tests + 18 dbt tests, all passing.
- Pushed to `main` on [wirkix/motor-analytics](https://github.com/wirkix/motor-analytics).
- Portfolio card on the professional-website site updated (tech chips only —
  no live demo link yet, see "Scope decided" below).

The committed `data/motor_analytics.duckdb` currently reflects the
~150-row **synthetic fixture**, not the real dataset — that's the first
thing below.

## Next steps — three things only you can unblock

### 1. Real dataset (Kaggle)

Download `austinreese/craigslist-carstrucks-data` (~426k rows, ~1.45GB —
never committed to git, `data/raw/` is gitignored):

```bash
kaggle datasets download -d austinreese/craigslist-carstrucks-data -p data/raw --unzip
```

Needs a free Kaggle account + API token
([instructions](https://www.kaggle.com/docs/api)) — Claude can't
authenticate to Kaggle on your behalf. Then in `.env`:

```
RAW_CSV_PATH=data/raw/vehicles.csv
```

### 2. Banxico API token

Free registration:
<https://www.banxico.org.mx/SieAPIRest/service/v1/token>. Then in `.env`:

```
BANXICO_TOKEN=<your token>
```

Optional in the sense that the pipeline already runs without it (flagged
fallback FX/INPC data) — but the project's headline feature, a real
inflation-adjusted MXN price, needs it to be real.

### 3. Anthropic API key

For the Streamlit chat agent to actually run — not yet smoke-tested live,
no key was available in the build session. In `.env`:

```
ANTHROPIC_API_KEY=<your key>
# optional, defaults to claude-opus-5:
ANTHROPIC_MODEL=claude-sonnet-5   # or claude-haiku-4-5 for a cheaper/faster demo
```

### Then, rebuild for real

```bash
python -m ingest.run
python -m enrich.run
dbt build --project-dir dbt --profiles-dir dbt
streamlit run app/streamlit_app.py    # try it locally
```

Commit the regenerated `data/motor_analytics.duckdb` once it looks right —
that's what makes the demo runnable with zero setup for anyone else who
clones the repo.

## Scope decided, not a blocker

- **No live deployment yet.** Streamlit runs locally against the committed
  `.duckdb`; the portfolio card links to GitHub only (`demo: null`),
  deliberately, until there's a plan for hosting a real Anthropic API key
  as a secret (Streamlit Community Cloud + your GitHub, when you're ready).
- If/when a live demo happens, revisit the portfolio card the same way
  Job Market Radar got its report page + live thumbnail — see
  `professional-website/src/app/projects/job-market-radar/page.tsx` and
  the `LivePreview` component for the pattern to follow.

## Known gotcha if you touch this repo again

This dev machine's default Python (3.14) can't install `dbt-core` cleanly —
Avast's HTTPS-scanning proxy breaks a raw network-fetch step inside one of
its sub-dependencies on very new Python. Fix: use Python 3.12 for this
project's venv (`py -3.12 -m venv .venv`) — installed via
`winget install --id Python.Python.3.12 -e --source winget`. Full
explanation in `CLAUDE.md`.
