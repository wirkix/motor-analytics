"""Process & enrich entrypoint: fetch Banxico FX + INPC for the ingested
listings' posting-date range and land it as raw.fx_inpc_daily. Run as
`python -m enrich.run`, after `python -m ingest.run`.

Falls back to a flagged constant table (see enrich/banxico.py) if
BANXICO_TOKEN is unset or the API call fails, instead of hard-failing — the
rest of the pipeline (dbt build, the Streamlit app) stays fully demoable
either way.
"""
import os
import sys

import duckdb
from dotenv import load_dotenv

from enrich.banxico import build_reference_table, fallback_reference_table, fetch_raw
from ingest.config import DUCKDB_PATH, RAW_SCHEMA

load_dotenv()

REFERENCE_TABLE = "fx_inpc_daily"


def _posting_date_range(duckdb_path) -> tuple:
    con = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        row = con.execute(
            f"select min(posting_date)::date, max(posting_date)::date "
            f"from {RAW_SCHEMA}.used_car_listings"
        ).fetchone()
    finally:
        con.close()
    if row is None or row[0] is None:
        raise RuntimeError(
            "raw.used_car_listings is empty — run `python -m ingest.run` first."
        )
    return row[0], row[1]


def main() -> None:
    start_date, end_date = _posting_date_range(DUCKDB_PATH)
    print(f"Posting-date range: {start_date} .. {end_date}")

    token = os.getenv("BANXICO_TOKEN", "").strip()
    if not token:
        print(
            "BANXICO_TOKEN not set - using flagged fallback FX/INPC data. "
            "See .env.example for how to get a free token.",
            file=sys.stderr,
        )
        df = fallback_reference_table(start_date, end_date)
    else:
        try:
            raw = fetch_raw(token, start_date, end_date)
            df = build_reference_table(raw, start_date, end_date)
            print(f"  fetched {len(df)} days from Banxico SIE API")
        except Exception as exc:  # noqa: BLE001 — any failure falls back, doesn't crash the pipeline
            print(f"Banxico API call failed ({exc}) — using flagged fallback data.", file=sys.stderr)
            df = fallback_reference_table(start_date, end_date)

    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        con.execute(f"create schema if not exists {RAW_SCHEMA}")
        con.register("df_view", df)
        con.execute(
            f"create or replace table {RAW_SCHEMA}.{REFERENCE_TABLE} as select * from df_view"
        )
        con.unregister("df_view")
    finally:
        con.close()

    fallback_note = " (fallback)" if df["is_fallback"].iloc[0] else ""
    print(f"Loaded raw.{REFERENCE_TABLE}{fallback_note}: {len(df)} rows.")


if __name__ == "__main__":
    main()
