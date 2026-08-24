# CLAUDE.md

Guidance for Claude Code (and future contributors) working in this repo.

## What this is

Portfolio project #2 of a six-project roadmap (see [Job Market
Radar](https://github.com/wirkix/job-market-radar) for #1). A wide,
denormalized used-car listings table — deliberately not star-schemed —
queried by Claude via tool use instead of a fixed BI dashboard. See
[README.md](README.md) for the full architecture/setup/data-model writeup
aimed at a human; this file is the non-obvious "why" and footgun list.

## Repo layout

```
ingest/      Extract & clean (Pandas) — CSV in, raw.used_car_listings out
enrich/      Process & enrich (Banxico SIE API) — raw.fx_inpc_daily out
dbt/         staging (views) -> marts (fct_used_car_listing, the wide table)
app/         Streamlit chat + the Claude tool-use loop that answers it
tests/       pytest — pure logic + one end-to-end query against the
             committed .duckdb file
data/
  raw/       gitignored — user drops the real Kaggle CSV here
  fixtures/  committed — synthetic CSV + Banxico JSON, used by ingest/enrich
             with zero external inputs and by the test suite
  motor_analytics.duckdb   COMMITTED build artifact — see below
```

No `airflow/`, `docker/`, `docker-compose.yml` — unlike job-market-radar,
this stack has no orchestrator and no server database. Every stage is a
plain `python -m X.run` entrypoint against one embedded DuckDB file.
Don't add Docker/Airflow here; there's no live/scheduled source to justify
the machinery, and the whole point of this project vs. #1 is a lighter,
purely local/free stack.

## Python version — must be 3.11 or 3.12, NOT 3.13+

This machine's default Python (checked via `py -0p`) may be newer than
dbt-core supports. `dbt-core`'s dependency `dbt-core-experimental-parser`
has no prebuilt wheel for very new CPython releases; pip falls back to
building its sdist, whose build backend does a **raw, unverified-by-pip**
`urlopen()` fetch of a prebuilt wheel from a GitHub release — and on this
dev machine, Avast's HTTPS-scanning proxy injects a root cert with a
Basic-Constraints extension not marked critical, which newer OpenSSL/Python
ssl builds reject outright (`CERTIFICATE_VERIFY_FAILED: Basic Constraints
of CA cert not marked critical`). Neither `SSL_CERT_FILE` nor
`REQUESTS_CA_BUNDLE` fixes it — the failing subprocess doesn't inherit them
the same way. The actual fix: use Python 3.12 for this project's venv
(`py -3.12 -m venv .venv`), where `dbt-core-experimental-parser` has a real
wheel and never hits this path. Installed via
`winget install --id Python.Python.3.12 -e --source winget` (add
`--source winget` explicitly — the default `msstore` source hits the same
Avast interception issue on its own cert check and fails first).

## dbt

- `dbt/profiles.yml` is safe to commit — the only value is
  `env_var('DUCKDB_PATH', ...)`. **Always invoke dbt from the repo root**
  (`dbt build --project-dir dbt --profiles-dir dbt`), never `cd dbt && dbt
  build` — the path is relative to the invoking shell's cwd, and it has to
  resolve to the same file `ingest`/`enrich` just wrote to, or dbt silently
  builds against (and creates) a different, empty database file.
- `accepted_values` tests must nest `values` under an `arguments:` key
  (`accepted_values: {arguments: {values: [...]}}`) — the older flat form
  (`accepted_values: {values: [...]}`) still runs but prints a
  `MissingArgumentsPropertyInGenericTestDeprecation` warning on this dbt
  version. Use the nested form in any new test.
- No `dbt_utils` dependency, same as job-market-radar — `id` (Craigslist's
  own listing id) is already a stable natural key for a single wide table,
  no surrogate key needed.
- `dbt/models/marts/schema.yml`'s column `description`s are not just docs —
  `app/schema_context.py` parses this file at runtime to build the Claude
  agent's schema context. Adding/renaming a column in
  `fct_used_car_listing.sql` without a matching `schema.yml` entry means
  the agent won't know that column exists.

## Banxico enrichment

- Two series: **SF43718** (daily FX fix rate) and **SP1** (monthly INPC).
  Banxico marks missing observations as the literal string `"N/E"` — parsed
  as real `NaN`s in `enrich/banxico.py`, not zeros.
- Both series get forward-filled (then back-filled, for any leading gap) to
  a dense daily calendar in Python, specifically so the dbt join is a plain
  `=` on date instead of an as-of/nearest-date join. If you're tempted to
  move this into dbt/SQL for "purity," don't — the date-alignment logic is
  clearer in pandas and dbt-duckdb doesn't make an as-of join notably nicer.
- `BANXICO_TOKEN` unset (or the API call failing) is a **handled path, not
  an error** — `enrich/run.py` writes a flagged constant fallback
  (`fx_rate=17.5`, `inpc` ratio neutralized to `1.0`,
  `is_fallback=true`) so the rest of the pipeline stays buildable/demoable.
  `fct_used_car_listing.is_fx_fallback_data` propagates the flag; don't
  remove it or the fallback data becomes indistinguishable from real
  historical rates downstream.

## The Claude chat agent (`app/`)

- Manual tool-use loop (`app/claude_agent.py`), not the SDK's beta tool
  runner — deliberately, because the Streamlit UI needs the exact SQL each
  turn ran (for the "SQL run" expander), which is much more direct to pull
  out of a hand-written loop than the tool runner's per-iteration message
  stream.
- `app/sql_tool.py`'s guard is defense **in depth**, not the only
  protection — the DuckDB connection itself is opened `read_only=True`,
  which is the real backstop. Don't remove the regex guard on the theory
  that read-only mode alone is enough; keep both.
- Before touching `claude_agent.py`'s request shape (model id, `tools`,
  `system`, thinking/effort params), re-check the `claude-api` skill rather
  than trusting memory — this is exactly the kind of file the skill's
  "API drift" warning is about.

## Known gotchas / history

- **`pandas` 3.x removed `include_groups=True`** on `GroupBy.apply` —
  `ingest/clean.py::stratified_sample` was originally written with
  `groupby(...).apply(..., include_groups=True)` and had to be rewritten as
  a plain per-group loop + `pd.concat`. If you see
  `ValueError: include_groups=True is no longer allowed`, this is why.
- **Proportional (`frac=`) stratified sampling silently drops rare
  groups.** The first version of `stratified_sample` used
  `group.sample(frac=frac)` per manufacturer group — for a rare brand with
  e.g. 3 listings and an overall sampling fraction of ~0.12, `3 * 0.12 =
  0.36` rounds to **0**, so the brand vanishes entirely, defeating the
  entire point of stratifying. Fixed by using
  `max(1, round(len(group) * frac))` per group instead, which guarantees
  every manufacturer with at least one listing survives sampling, at the
  cost of a small (usually negligible) overshoot past the target `n` when
  there are many tiny groups. Covered by
  `tests/test_clean.py::test_stratified_sample_keeps_rare_manufacturers`.
- **The committed `.duckdb` is currently built from the synthetic fixture**,
  not the real Kaggle dataset — see README "Known limitations". Rebuild and
  recommit once the real CSV + a Banxico token are available.
