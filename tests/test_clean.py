import pandas as pd
import pytest

from ingest.clean import (
    clean,
    coerce_numeric,
    dedupe,
    derive_has_vin,
    drop_noise_columns,
    normalize_text,
    stratified_sample,
)
from ingest.config import RAW_CSV_PATH


@pytest.fixture(scope="module")
def raw_df() -> pd.DataFrame:
    return pd.read_csv(RAW_CSV_PATH, low_memory=False)


def test_fixture_has_exact_duplicate_ids(raw_df):
    # Sanity check on the fixture itself — dedupe has nothing to prove
    # against otherwise.
    assert raw_df["id"].duplicated().sum() >= 1


def test_dedupe_drops_duplicate_ids(raw_df):
    deduped = dedupe(raw_df)
    assert deduped["id"].is_unique
    assert len(deduped) < len(raw_df)


def test_normalize_text_lowercases_and_strips():
    df = pd.DataFrame({"manufacturer": [" Ford ", "TOYOTA", None, ""]})
    out = normalize_text(df)
    assert out["manufacturer"].tolist()[:2] == ["ford", "toyota"]
    assert pd.isna(out["manufacturer"].iloc[2])
    assert pd.isna(out["manufacturer"].iloc[3])  # empty string -> null, not a category


def test_coerce_numeric_handles_junk():
    df = pd.DataFrame({"price": ["1000", "not-a-number", None, "-500"]})
    out = coerce_numeric(df)
    assert out["price"].tolist()[0] == 1000.0
    assert pd.isna(out["price"].iloc[1])
    assert out["price"].iloc[3] == -500.0  # negative survives here — stg_used_car_listings filters it, not this


def test_derive_has_vin():
    df = pd.DataFrame({"VIN": ["1HGCM82633A123456", "", None, "too-short"]})
    out = derive_has_vin(df)
    assert out["has_vin"].tolist() == [True, False, False, False]


def test_drop_noise_columns():
    df = pd.DataFrame({"url": ["x"], "description": ["y"], "id": [1]})
    out = drop_noise_columns(df)
    assert list(out.columns) == ["id"]


def test_stratified_sample_no_ops_under_target(raw_df):
    cleaned = clean(raw_df)
    sampled = stratified_sample(cleaned, n=len(cleaned) + 1000, seed=42)
    assert len(sampled) == len(cleaned)


def test_stratified_sample_keeps_rare_manufacturers():
    df = pd.DataFrame({
        "manufacturer": ["ford"] * 100 + ["rare-brand"] * 2,
        "id": range(102),
    })
    sampled = stratified_sample(df, n=20, seed=42)
    assert "rare-brand" in sampled["manufacturer"].values


def test_clean_end_to_end_drops_noise_and_dedupes(raw_df):
    out = clean(raw_df)
    assert out["id"].is_unique
    assert "url" not in out.columns
    assert "VIN" not in out.columns
    assert "has_vin" in out.columns
