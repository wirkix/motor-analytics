"""Pandas cleaning for the raw Craigslist export. Deliberately does NOT drop
bad rows (price <= 0, out-of-range year, etc.) — that filtering happens in
dbt's staging layer (stg_used_car_listings.sql) so it's visible/testable SQL
rather than silent Python logic. This module only: dedupes, normalizes text
casing, coerces numeric typing, derives has_vin, and drops noise columns.
"""
import re

import pandas as pd

from ingest.config import DROP_COLUMNS

TEXT_COLUMNS = [
    "region", "manufacturer", "model", "condition", "cylinders", "fuel",
    "title_status", "transmission", "drive", "size", "type", "paint_color",
    "state",
]
NUMERIC_COLUMNS = ["price", "year", "odometer", "lat", "long"]


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """The Craigslist export has exact-duplicate rows (same listing scraped
    twice). `id` is the dataset's own stable unique key — no surrogate key
    needed downstream."""
    return df.drop_duplicates(subset="id", keep="first")


def normalize_text(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + strip whitespace on categorical/brand/model text so
    'Ford', ' ford ', 'FORD' don't fragment into separate groups. Empty
    strings become real nulls — a blank manufacturer is not a category."""
    df = df.copy()
    for col in TEXT_COLUMNS:
        if col not in df.columns:
            continue
        df[col] = df[col].astype("string").str.strip().str.lower()
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA})
    return df


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """price/year/odometer/lat/long as real numeric types — the source CSV
    can carry stray non-numeric junk (Kaggle's version has some), which
    becomes NaN here rather than silently coercing the whole column to
    object dtype."""
    df = df.copy()
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$", re.IGNORECASE)


def derive_has_vin(df: pd.DataFrame) -> pd.DataFrame:
    """A syntactically-plausible VIN is a signal (more complete listing),
    but the raw VIN string itself is dropped — it's an identifier, not an
    analytics column, and keeping thousands of them serves no purpose here."""
    df = df.copy()
    vin = df.get("VIN", pd.Series(dtype="string")).astype("string").str.strip()
    df["has_vin"] = vin.fillna("").str.match(_VIN_RE)
    return df


def drop_noise_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in DROP_COLUMNS if c in df.columns])


def stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Samples down to around `n` rows, stratified by manufacturer so rare
    brands don't vanish entirely under a plain random sample. Rows with a
    null manufacturer are treated as their own group.

    Each group gets max(1, round(group_size * frac)) rows — the floor of 1
    is deliberate: a plain `frac`-based sample rounds a small group (e.g. 3
    rows at frac=0.12) down to 0 and drops the brand entirely, which is
    exactly what stratifying was supposed to prevent. This can overshoot
    `n` slightly when there are many tiny groups (each contributes its
    floor of 1); that's an acceptable tradeoff for "every manufacturer with
    at least one listing survives sampling." No-ops if the frame is already
    at or below `n` (true for the fixture CSV).
    """
    if len(df) <= n:
        return df
    frac = n / len(df)
    groups = df.groupby(df["manufacturer"].fillna("__unknown__"))
    sampled = []
    for _, group in groups:
        group_n = min(len(group), max(1, round(len(group) * frac)))
        sampled.append(group.sample(n=group_n, random_state=seed))
    return pd.concat(sampled, ignore_index=True)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Full cleaning pipeline, in order. Sampling is a separate step (see
    ingest/run.py) — it runs after cleaning so the sample is drawn from
    deduped, typed data."""
    df = dedupe(df)
    df = normalize_text(df)
    df = coerce_numeric(df)
    df = derive_has_vin(df)
    df = drop_noise_columns(df)
    return df
