-- Grain: one row per calendar day. Straight passthrough of raw.fx_inpc_daily
-- — the forward-fill/fallback logic already happened in Python
-- (enrich/banxico.py) because it's a date-alignment problem, not something
-- SQL does more clearly. This model exists so downstream marts reference a
-- staging model like every other source, not the raw schema directly.

select
    calendar_date,
    fx_rate,
    inpc_index,
    inpc_reference_period,
    is_fallback
from {{ source('raw', 'fx_inpc_daily') }}
