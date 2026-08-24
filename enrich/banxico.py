"""Banxico SIE API client: fetches the daily FX fix rate (series SF43718)
and the monthly INPC inflation index (series SP1) for the dataset's posting-
date range, in one multi-series call, and forward-fills both onto a dense
daily calendar so dbt can join against it with a plain equi-join instead of
an as-of/nearest-date join.

Docs: https://www.banxico.org.mx/SieAPIRest/service/v1/doc/index.html
Free token: https://www.banxico.org.mx/SieAPIRest/service/v1/token

FX/inflation formula this table feeds (see dbt/models/marts/fct_used_car_listing.sql):

    price_mxn_nominal_at_post_date = price_usd * fx_rate_at_post_date
    price_mxn_inflation_adjusted   = price_usd * fx_rate_at_post_date
                                      * (inpc_latest / inpc_at_post_month)
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

SERIES_FX = "SF43718"  # Tipo de cambio FIX, pesos por USD
SERIES_INPC = "SP1"  # INPC general
FALLBACK_FX_RATE = 17.5
BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"

REFERENCE_COLUMNS = [
    "calendar_date", "fx_rate", "inpc_index", "inpc_reference_period", "is_fallback",
]


def fetch_raw(token: str, start_date: dt.date, end_date: dt.date) -> dict:
    """One HTTP call for both series. Raises for network/HTTP errors —
    callers decide whether to fall back (see enrich/run.py)."""
    series_ids = f"{SERIES_FX},{SERIES_INPC}"
    url = f"{BASE_URL}/{series_ids}/datos/{start_date:%Y-%m-%d}/{end_date:%Y-%m-%d}"
    resp = requests.get(url, headers={"Bmx-Token": token}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_series(raw: dict) -> dict[str, pd.Series]:
    """Banxico marks missing observations as the literal string "N/E"
    (banking holidays for the daily FX series, unpublished months for the
    monthly INPC series) — those become real NaNs, not zeros."""
    out: dict[str, pd.Series] = {}
    for series in raw.get("bmx", {}).get("series", []):
        dates, values = [], []
        for point in series.get("datos", []):
            dates.append(pd.to_datetime(point["fecha"], format="%d/%m/%Y"))
            raw_val = point["dato"]
            values.append(float(raw_val) if raw_val not in ("N/E", "", None) else None)
        out[series["idSerie"]] = pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()
    return out


def build_reference_table(raw: dict, start_date: dt.date, end_date: dt.date) -> pd.DataFrame:
    """Forward-fills both series onto every calendar day in [start_date,
    end_date] (weekends/holidays/unpublished months inherit the last known
    value); back-fills any leading gap so the very first day(s) aren't
    null if Banxico's first observation lands after start_date."""
    parsed = _parse_series(raw)
    calendar = pd.date_range(start_date, end_date, freq="D")

    fx = parsed.get(SERIES_FX, pd.Series(dtype=float)).reindex(calendar).ffill().bfill()
    inpc = parsed.get(SERIES_INPC, pd.Series(dtype=float)).reindex(calendar).ffill().bfill()

    # Which INPC observation date is "in effect" for each calendar day —
    # carried forward alongside the value itself, for the app/report to
    # surface as inpc_reference_period rather than silently baking it in.
    inpc_obs_dates = parsed.get(SERIES_INPC, pd.Series(dtype=float))
    inpc_period = (
        pd.Series(inpc_obs_dates.index, index=inpc_obs_dates.index)
        .reindex(calendar)
        .ffill()
        .bfill()
    )

    return pd.DataFrame({
        "calendar_date": calendar,
        "fx_rate": fx.values,
        "inpc_index": inpc.values,
        "inpc_reference_period": pd.to_datetime(inpc_period.values).date,
        "is_fallback": False,
    })


def fallback_reference_table(start_date: dt.date, end_date: dt.date) -> pd.DataFrame:
    """Used when BANXICO_TOKEN is unset or the API call fails — keeps the
    whole pipeline buildable/demoable. fx_rate is a rough constant, the INPC
    ratio is neutralized to 1.0 (inflation_adjustment_factor == fx_rate),
    and every row is flagged is_fallback=true so it's never mistaken for
    real historical data downstream."""
    calendar = pd.date_range(start_date, end_date, freq="D")
    return pd.DataFrame({
        "calendar_date": calendar,
        "fx_rate": FALLBACK_FX_RATE,
        "inpc_index": 1.0,
        "inpc_reference_period": None,
        "is_fallback": True,
    })
