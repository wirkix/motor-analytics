import datetime as dt
import json
from pathlib import Path

from enrich.banxico import (
    FALLBACK_FX_RATE,
    build_reference_table,
    fallback_reference_table,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "sample_fx_inpc.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_build_reference_table_forward_fills_every_day():
    raw = _load_fixture()
    df = build_reference_table(raw, dt.date(2021, 4, 1), dt.date(2021, 6, 30))
    assert len(df) == 91  # April(30) + May(31) + June(30)
    assert df["fx_rate"].isna().sum() == 0
    assert df["inpc_index"].isna().sum() == 0
    assert (df["is_fallback"] == False).all()  # noqa: E712


def test_build_reference_table_ffills_known_values_forward():
    raw = _load_fixture()
    df = build_reference_table(raw, dt.date(2021, 4, 1), dt.date(2021, 6, 30))
    # Fixture's first FX observation is 20.4381 on 2021-04-01 — every day up
    # to (not including) the next observation (2021-04-15) should carry it.
    first_week = df[df["calendar_date"] < "2021-04-15"]
    assert (first_week["fx_rate"] == 20.4381).all()


def test_build_reference_table_carries_inpc_reference_period():
    raw = _load_fixture()
    df = build_reference_table(raw, dt.date(2021, 4, 1), dt.date(2021, 6, 30))
    june_row = df[df["calendar_date"] == "2021-06-15"].iloc[0]
    assert str(june_row["inpc_reference_period"]) == "2021-06-01"


def test_fallback_reference_table_is_flagged_and_neutral():
    df = fallback_reference_table(dt.date(2021, 1, 1), dt.date(2021, 1, 5))
    assert len(df) == 5
    assert (df["is_fallback"] == True).all()  # noqa: E712
    assert (df["fx_rate"] == FALLBACK_FX_RATE).all()
    assert (df["inpc_index"] == 1.0).all()  # neutralizes the inflation ratio to 1.0
