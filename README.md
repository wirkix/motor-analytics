# Wide-Table Motor Analytics

One denormalized, one-row-per-listing table over a public used-car dataset —
built deliberately **wide** instead of star-schemed, then queried by an LLM
analyst (Claude, via tool use) instead of a fixed dashboard.

Built as a portfolio piece to demonstrate the *other* half of a modeling
decision: [Job Market Radar](https://github.com/wirkix/job-market-radar) is
a classic Kimball star schema; this project is the same skillset applied to
the opposite shape on purpose, with a working example of why a wide mart is
what an AI analyst actually wants to scan — one table, no joins, every
filterable column already sitting on the row.

## Architecture

```
      Kaggle: Craigslist cars/trucks CSV        Banxico SIE API
       (~426k rows, USD, user-downloaded)      (SF43718 FX + SP1 INPC)
                    │                                  │
                    ▼                                  ▼
              ingest/ (Pandas)                   enrich/ (requests)
     clean, normalize, stratified sample      forward-fill to a daily
       by manufacturer, drop noise cols       calendar; flagged fallback
                    │                          if no BANXICO_TOKEN
                    ▼                                  │
       DuckDB: raw.used_car_listings                   ▼
                    │                    DuckDB: raw.fx_inpc_daily
                    └──────────────┬─────────────────────┘
                                   ▼
                          dbt (staging → marts)
                                   │
                                   ▼
                 ┌───────────────────────────────────┐
                 │  fct_used_car_listing              │
                 │  one wide table, ~65 columns:      │
                 │  identity · age/mileage · USD &    │
                 │  Banxico-driven MXN price ·        │
                 │  powertrain · body/condition ·     │
                 │  data-quality flags                │
                 └───────────────────────────────────┘
                                   │
                                   ▼
                     app/ — Streamlit chat, answered
                     live by Claude via a run_sql tool
                     against the table directly
```

Everything is local/embedded — a single `.duckdb` file, no server, no
Docker, no orchestrator. Contrast with Job Market Radar's Postgres +
Airflow stack: that project needed orchestration because it runs on a
schedule against a live source; this one is a point-in-time analytical
table built from a static dataset, so a plain Python entrypoint per stage
is all the "orchestration" it needs.

## Why wide instead of star

A star schema pays off when many fact tables share the same dimensions and
you want consistent, reusable joins (`dim_company`, `dim_date`, ... across
several facts — see Job Market Radar). Here there's exactly one entity
(a listing) and exactly one consumer that matters: an LLM that has to
decide, per question, what to `GROUP BY` and `WHERE`. Every join the model
would otherwise have to get right — listing → make/model lookup, listing →
FX rate on that date — is pre-resolved onto the row instead. The tradeoff
is real (this table duplicates the FX/INPC value onto every listing from
that day, instead of a dimension table storing it once) — it's a
deliberate, documented one, not an oversight.

## Setup

**Requires:** Python 3.11–3.12 (dbt-core's `dbt-core-experimental-parser`
dependency has no prebuilt wheel yet for very new Python releases and falls
back to a network-fetching sdist build — avoid Python 3.13+ for this
project's venv until that catches up).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env
```

Works with **zero further setup** against the bundled fixture dataset
(`data/fixtures/sample_listings.csv`, ~150 synthetic rows) and the
committed `data/motor_analytics.duckdb` — `streamlit run app/streamlit_app.py`
runs immediately once `ANTHROPIC_API_KEY` is set in `.env`.

To build against the **real** dataset:

1. **Kaggle dataset** (Python/Pandas ingest input): download
   [`austinreese/craigslist-carstrucks-data`](https://www.kaggle.com/datasets/austinreese/craigslist-carstrucks-data)
   (requires a free Kaggle account + API token —
   [instructions](https://www.kaggle.com/docs/api)):
   ```bash
   kaggle datasets download -d austinreese/craigslist-carstrucks-data -p data/raw --unzip
   ```
   This lands `data/raw/vehicles.csv` (~1.45GB) — gitignored, never
   committed. Set `RAW_CSV_PATH=data/raw/vehicles.csv` in `.env`.

2. **Banxico SIE API token** (FX + inflation enrichment): register for a
   free token at
   [banxico.org.mx/SieAPIRest/service/v1/token](https://www.banxico.org.mx/SieAPIRest/service/v1/token)
   and set `BANXICO_TOKEN` in `.env`. Optional — `enrich/run.py` falls back
   to a flagged constant instead of failing if this is blank (see
   `enrich/banxico.py`).

3. **Anthropic API key** (the chat agent): set `ANTHROPIC_API_KEY` in
   `.env`. Defaults to `claude-opus-5` — set `ANTHROPIC_MODEL` to
   `claude-sonnet-5` or `claude-haiku-4-5` for a cheaper/faster demo.

```bash
python -m ingest.run                                    # -> raw.used_car_listings
python -m enrich.run                                     # -> raw.fx_inpc_daily
dbt build --project-dir dbt --profiles-dir dbt            # -> main_marts.fct_used_car_listing
streamlit run app/streamlit_app.py
```

Always run `dbt` from the repo root (`--project-dir dbt --profiles-dir dbt`),
not `cd dbt && dbt build` — `DUCKDB_PATH` in `profiles.yml` is relative to
the invoking shell's working directory, and it needs to resolve to the same
file `ingest`/`enrich` just wrote to.

## Running pieces individually

Each stage is a plain Python entrypoint — no orchestrator required:

```bash
python -m ingest.run     # extract & clean
python -m enrich.run     # Banxico FX/INPC enrichment
dbt build --project-dir dbt --profiles-dir dbt   # the wide mart
streamlit run app/streamlit_app.py                # the chat UI
```

## Tests

```bash
pytest
```

Pure logic (Pandas cleaning, Banxico forward-fill math, the SQL tool's
write/DDL guard) plus an end-to-end query against the committed
`.duckdb` file — the latter is there specifically so a real regression in
the built table (not just the code) fails a test, not just a demo.

## Data model

One wide table, `main_marts.fct_used_car_listing` — grain: one row per
listing. See `dbt/models/marts/schema.yml` for the full column-by-column
reference (same file the Streamlit app parses at runtime for the LLM's
schema context — the docs can't silently drift out of sync with what the
agent knows). Broad strokes:

- **Identity & geography** — id, region/state, US Census region, border-state flag, lat/long
- **Listing metadata** — posting date/year/month/quarter/season, days since posting (relative to the dataset, not wall-clock)
- **Brand/model** — normalized manufacturer/model, hand-rolled brand tier (economy/mainstream/luxury/exotic)
- **Age/mileage** — vehicle age (relative to the listing date), bucketed age/mileage, miles/year, high-mileage-for-age flag
- **Price (USD)** — raw price, bucketed, price-per-mile, z-score vs. the listing's own manufacturer, outlier flag
- **Price (MXN, Banxico-driven)** — the project's headline enrichment: nominal and inflation-adjusted MXN price, the FX rate and INPC values behind it, and an `is_fx_fallback_data` flag when built without a real Banxico token
- **Powertrain** — fuel/transmission/drive, one-hot-ish boolean flags for each, cylinder count/bucket
- **Body/condition** — vehicle type, condition, title status, has-VIN, paint color
- **Data quality** — missing-field flags, a per-row completeness score

## Known limitations

- **The committed `.duckdb` reflects whichever dataset it was last built
  against.** As of 2026-08-23 it's built from the real Kaggle CSV
  (~50k-listing stratified sample) with real Banxico FX/INPC data — not the
  synthetic fixture. If you rebuild locally without both `RAW_CSV_PATH` and
  `BANXICO_TOKEN` set in `.env`, you'll silently get the fixture/fallback
  version back; check `is_fx_fallback_data` before recommitting.
- **The Kaggle dataset is Craigslist listings, all USD-denominated** — the
  MXN enrichment converts/inflation-adjusts USD prices rather than working
  from native Mexican listings. That's intentional (a public, richly
  featured used-car dataset with the same granularity in Spanish/MXN isn't
  as readily available), but it means the MXN columns are a currency/
  inflation lens on a US market, not a real Mexican used-car market signal.
- **`inpc_index_latest` is a build-time constant**, not a live figure — see
  `is_fx_fallback_data`/`inpc_reference_period` on the table, and the
  formula write-up in `dbt/models/marts/fct_used_car_listing.sql`.
- **No live deployment.** The Streamlit app runs locally against the
  committed `.duckdb` — see the portfolio site for why (managing a hosted
  Anthropic API key secret is a deliberate follow-up, not done here yet).
