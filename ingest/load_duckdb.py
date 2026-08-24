"""Lands the cleaned DataFrame into the raw schema of the project's single
DuckDB file. No server, no migrations — dbt-duckdb reads straight from this
table via its `raw.used_car_listings` source."""
import duckdb
import pandas as pd

from ingest.config import DUCKDB_PATH, RAW_SCHEMA, RAW_TABLE


def load(df: pd.DataFrame, duckdb_path=DUCKDB_PATH) -> None:
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute(f"create schema if not exists {RAW_SCHEMA}")
        # register() + CREATE OR REPLACE TABLE ... AS SELECT * FROM df_view
        # is DuckDB's idiomatic zero-copy way to land a pandas DataFrame —
        # no ORM, no row-by-row inserts.
        con.register("df_view", df)
        con.execute(
            f"create or replace table {RAW_SCHEMA}.{RAW_TABLE} as select * from df_view"
        )
        con.unregister("df_view")
    finally:
        con.close()
