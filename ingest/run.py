"""Extract & clean entrypoint: read the raw CSV -> clean -> stratified
sample -> land in DuckDB. Run as `python -m ingest.run`.

Defaults to the bundled fixture (data/fixtures/sample_listings.csv) so this
works with zero setup; point RAW_CSV_PATH (.env) at the real Kaggle export
to build the full wide table.
"""
import sys

import pandas as pd

from ingest.clean import clean, stratified_sample
from ingest.config import RANDOM_SEED, RAW_CSV_PATH, SAMPLE_SIZE
from ingest.load_duckdb import load


def main() -> None:
    if not RAW_CSV_PATH.exists():
        print(f"RAW_CSV_PATH not found: {RAW_CSV_PATH}", file=sys.stderr)
        print(
            "Download the Kaggle dataset or point RAW_CSV_PATH at a CSV "
            "shaped like it (see .env.example / README).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Reading {RAW_CSV_PATH} ...")
    df = pd.read_csv(RAW_CSV_PATH, low_memory=False)
    print(f"  {len(df):,} raw rows")

    df = clean(df)
    print(f"  {len(df):,} rows after cleaning/dedup")

    df = stratified_sample(df, SAMPLE_SIZE, RANDOM_SEED)
    print(f"  {len(df):,} rows after sampling (target {SAMPLE_SIZE:,})")

    load(df)
    print("Loaded raw.used_car_listings.")


if __name__ == "__main__":
    main()
