"""Env-driven configuration for the ingest stage. Every value has a sane
default so `python -m ingest.run` works against the bundled fixture with no
.env file at all — only real runs against the full Kaggle CSV need .env set.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent

RAW_CSV_PATH = Path(os.getenv("RAW_CSV_PATH", "data/fixtures/sample_listings.csv"))
DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", "data/motor_analytics.duckdb"))

# Stratified-by-manufacturer sample size. The fixture CSV is only ~150 rows,
# so a default of 50,000 would just keep every row — SAMPLE_SIZE only bites
# once RAW_CSV_PATH points at the real ~426k-row Kaggle file.
SAMPLE_SIZE = int(os.getenv("SAMPLE_SIZE", "50000"))
RANDOM_SEED = 42

# Columns dropped before landing in DuckDB — free text / URLs / near-always-
# null fields that aren't the point of a structured analytics table. VIN is
# dropped too, but only after clean.py derives a has_vin boolean from it.
DROP_COLUMNS = ["url", "region_url", "image_url", "description", "county", "VIN"]

RAW_SCHEMA = "raw"
RAW_TABLE = "used_car_listings"
