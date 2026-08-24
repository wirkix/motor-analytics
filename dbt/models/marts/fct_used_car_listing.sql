-- Grain: one row per used-car listing (stg_used_car_listings.id). This is
-- the whole point of the project — a deliberately wide, denormalized mart
-- instead of a star schema (contrast with job-market-radar's fact/dim
-- design), built so an LLM analyst can answer questions by scanning one
-- table instead of joining several.
--
-- FX/inflation math (see enrich/banxico.py for the full write-up):
--   price_mxn_nominal_at_post_date = price_usd * fx_rate_at_post_date
--   price_mxn_inflation_adjusted   = price_usd * fx_rate_at_post_date
--                                     * (inpc_latest / inpc_at_post_month)
-- inpc_latest is the most recent INPC value present in the FX/INPC
-- reference table as of when `enrich/run.py` last ran — baked in at build
-- time, not live. inpc_reference_period says which INPC reading is in
-- effect for a given listing's price_mxn_nominal_at_post_date.
-- is_fx_fallback_data = true means BANXICO_TOKEN wasn't set at build time
-- and every MXN figure here is a rough constant-rate conversion, not a real
-- historical FX/inflation adjustment — see .env.example.

with listings as (
    select * from {{ ref('stg_used_car_listings') }}
),

fx as (
    select * from {{ ref('stg_fx_inpc_reference') }}
),

latest_inpc as (
    -- Scalar: the single most recent INPC reading in the whole reference
    -- table, joined to every row below (cross join on a 1-row CTE).
    select
        inpc_index            as inpc_index_latest,
        inpc_reference_period as inpc_latest_period
    from fx
    qualify row_number() over (order by calendar_date desc) = 1
),

joined as (
    select
        l.*,
        fx.fx_rate             as fx_rate_at_post_date,
        fx.inpc_index          as inpc_index_at_post,
        fx.inpc_reference_period,
        fx.is_fallback          as is_fx_fallback_data,
        latest_inpc.inpc_index_latest,
        latest_inpc.inpc_latest_period
    from listings l
    left join fx
        on fx.calendar_date = l.posting_date
    cross join latest_inpc
),

derived as (
    select
        *,

        -- brand/model
        coalesce(manufacturer, 'unknown')  as manufacturer_clean,
        coalesce(model, 'unknown')         as model_clean,
        case
            when manufacturer in ('porsche', 'ferrari', 'maserati', 'bentley',
                                   'rolls-royce', 'lamborghini', 'aston-martin')
                then 'exotic'
            when manufacturer in ('bmw', 'mercedes-benz', 'audi', 'lexus',
                                   'tesla', 'land rover', 'jaguar', 'cadillac',
                                   'lincoln', 'acura', 'infiniti')
                then 'luxury'
            when manufacturer in ('hyundai', 'kia', 'mitsubishi', 'fiat',
                                   'suzuki', 'saturn')
                then 'economy'
            when manufacturer is null then 'unknown'
            else 'mainstream'
        end                                 as brand_tier,

        -- powertrain
        coalesce(fuel, 'unknown')          as fuel_type_clean,
        coalesce(transmission, 'unknown')  as transmission_clean,
        coalesce(drive, 'unknown')         as drive_clean,
        try_cast(regexp_extract(cylinders, '(\d+)', 1) as int) as cylinders_numeric,

        -- body/condition
        coalesce(vehicle_type, 'unknown')  as vehicle_type_clean,
        coalesce(size, 'unknown')          as size_clean,
        coalesce(condition, 'unknown')     as condition_clean,
        coalesce(title_status, 'unknown')  as title_status_clean,
        coalesce(region, 'unknown')        as region_clean,
        coalesce(state, 'unknown')         as state_clean,

        -- age (relative to posting date, not wall-clock, so this stays
        -- stable no matter when the table is rebuilt)
        greatest(date_part('year', posting_date) - year, 0) as vehicle_age_years,

        -- listing metadata
        date_part('year', posting_date)    as posting_year,
        date_part('month', posting_date)   as posting_month,
        date_part('quarter', posting_date) as posting_quarter,
        case
            when date_part('month', posting_date) in (12, 1, 2)  then 'winter'
            when date_part('month', posting_date) in (3, 4, 5)   then 'spring'
            when date_part('month', posting_date) in (6, 7, 8)   then 'summer'
            else 'fall'
        end as listing_season,
        date_diff('day', posting_date, max(posting_date) over ()) as days_since_posting,

        -- geography
        case
            when state in ('ct','me','ma','nh','ri','vt','nj','ny','pa') then 'Northeast'
            when state in ('il','in','mi','oh','wi','ia','ks','mn','mo','ne','nd','sd') then 'Midwest'
            when state in ('de','fl','ga','md','nc','sc','va','dc','wv','al','ky','ms','tn','ar','la','ok','tx') then 'South'
            when state in ('az','co','id','mt','nv','nm','ut','wy','ak','ca','hi','or','wa') then 'West'
            else 'unknown'
        end as state_region_group,
        (state in ('tx', 'ca', 'az', 'nm')) as is_border_state,

        -- MXN price (nominal + inflation-adjusted)
        price_usd * fx_rate_at_post_date as price_mxn_nominal_at_post_date,
        price_usd * fx_rate_at_post_date
            * (inpc_index_latest / nullif(inpc_index_at_post, 0)) as price_mxn_inflation_adjusted,
        fx_rate_at_post_date
            * (inpc_index_latest / nullif(inpc_index_at_post, 0)) as inflation_adjustment_factor,

        -- data quality
        (odometer_miles is null)   as is_missing_odometer,
        (manufacturer is null)     as is_missing_manufacturer,
        (
            (case when manufacturer is not null then 1 else 0 end) +
            (case when model is not null then 1 else 0 end) +
            (case when year is not null then 1 else 0 end) +
            (case when odometer_miles is not null then 1 else 0 end) +
            (case when condition is not null then 1 else 0 end) +
            (case when cylinders is not null then 1 else 0 end) +
            (case when fuel is not null then 1 else 0 end) +
            (case when title_status is not null then 1 else 0 end) +
            (case when transmission is not null then 1 else 0 end) +
            (case when drive is not null then 1 else 0 end) +
            (case when size is not null then 1 else 0 end) +
            (case when vehicle_type is not null then 1 else 0 end) +
            (case when paint_color is not null then 1 else 0 end)
        ) / 13.0 as completeness_score

    from joined
)

select
    -- identity
    id,
    region_clean                        as region,
    state_clean                         as state,
    state_region_group,
    is_border_state,
    lat,
    long,

    -- listing metadata
    posting_date,
    posting_year,
    posting_month,
    posting_quarter,
    listing_season,
    days_since_posting,

    -- brand/model
    manufacturer_clean                  as manufacturer,
    model_clean                         as model,
    brand_tier,
    (brand_tier in ('luxury', 'exotic')) as is_luxury_brand,
    (manufacturer_clean in (
        'ford', 'chevrolet', 'jeep', 'ram', 'cadillac', 'lincoln',
        'chrysler', 'dodge', 'buick', 'gmc', 'tesla'
    ))                                   as is_domestic_us_brand,
    (manufacturer_clean not in (
        'ford', 'chevrolet', 'jeep', 'ram', 'cadillac', 'lincoln',
        'chrysler', 'dodge', 'buick', 'gmc', 'tesla', 'unknown'
    ))                                   as is_import_brand,

    -- age/mileage
    year,
    vehicle_age_years,
    case
        when vehicle_age_years <= 2  then 'new'
        when vehicle_age_years <= 5  then 'recent'
        when vehicle_age_years <= 10 then 'mid'
        when vehicle_age_years <= 15 then 'old'
        else 'very_old'
    end                                  as age_bucket,
    odometer_miles,
    case
        when odometer_miles is null      then 'unknown'
        when odometer_miles < 30000      then 'low'
        when odometer_miles < 75000      then 'moderate'
        when odometer_miles < 150000     then 'high'
        else 'very_high'
    end                                  as mileage_bucket,
    round(odometer_miles / nullif(vehicle_age_years, 0), 0) as miles_per_year,
    (odometer_miles > vehicle_age_years * 15000)            as is_high_mileage_for_age,
    is_missing_odometer,

    -- price (USD)
    price_usd,
    case
        when price_usd < 5000  then 'budget'
        when price_usd < 15000 then 'economy'
        when price_usd < 30000 then 'mid'
        when price_usd < 60000 then 'premium'
        else 'luxury'
    end                                  as price_bucket,
    round(price_usd / nullif(odometer_miles, 0), 4) as price_per_mile,
    round(
        (price_usd - avg(price_usd) over (partition by manufacturer_clean))
        / nullif(stddev(price_usd) over (partition by manufacturer_clean), 0)
    , 3)                                  as price_zscore_by_manufacturer,
    (abs(
        (price_usd - avg(price_usd) over (partition by manufacturer_clean))
        / nullif(stddev(price_usd) over (partition by manufacturer_clean), 0)
    ) > 3)                                as is_price_outlier,

    -- price (MXN, Banxico-driven)
    fx_rate_at_post_date,
    inpc_index_at_post,
    inpc_index_latest,
    inpc_latest_period                   as inpc_reference_period,
    round(price_mxn_nominal_at_post_date, 2) as price_mxn_nominal_at_post_date,
    round(price_mxn_inflation_adjusted, 2)   as price_mxn_inflation_adjusted,
    round(inflation_adjustment_factor, 4)    as inflation_adjustment_factor,
    is_fx_fallback_data,

    -- powertrain
    fuel_type_clean                     as fuel_type,
    (fuel_type_clean = 'gas')           as is_gas,
    (fuel_type_clean = 'diesel')        as is_diesel,
    (fuel_type_clean = 'electric')      as is_electric,
    (fuel_type_clean = 'hybrid')        as is_hybrid,
    (fuel_type_clean in ('electric', 'hybrid')) as is_electric_or_hybrid,
    transmission_clean                  as transmission,
    (transmission_clean = 'automatic')  as is_automatic,
    (transmission_clean = 'manual')     as is_manual,
    drive_clean                         as drive,
    (drive_clean = '4wd')               as is_4wd,
    (drive_clean = 'fwd')               as is_fwd,
    (drive_clean = 'rwd')               as is_rwd,
    cylinders_numeric,
    case
        when cylinders_numeric is null then 'unknown'
        when cylinders_numeric <= 4    then 'low'
        when cylinders_numeric <= 6    then 'mid'
        when cylinders_numeric <= 8    then 'high'
        else 'very_high'
    end                                  as cylinder_bucket,

    -- body/condition
    vehicle_type_clean                  as vehicle_type,
    (vehicle_type_clean in ('truck', 'pickup')) as is_truck,
    (vehicle_type_clean = 'suv')                as is_suv,
    (vehicle_type_clean = 'sedan')              as is_sedan,
    (vehicle_type_clean = 'coupe')              as is_coupe,
    size_clean                          as size,
    condition_clean                     as condition,
    (condition_clean in ('new', 'like new', 'excellent')) as is_like_new_or_excellent,
    title_status_clean                  as title_status,
    (title_status_clean = 'clean')      as has_clean_title,
    has_vin,
    paint_color,

    -- data quality
    is_missing_manufacturer,
    round(completeness_score, 3)        as completeness_score

from derived
