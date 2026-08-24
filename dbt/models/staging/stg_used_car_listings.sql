-- Grain: one row per cleaned+sampled Craigslist listing (raw.used_car_listings),
-- minus rows that fail basic sanity checks. Filtering happens here, in SQL,
-- rather than silently in Pandas, so a listing being dropped is visible and
-- testable: price must be positive, year must fall in a plausible range.
-- These are deliberately loose bounds — the point is catching data-entry
-- garbage (price = -500, year = 0), not opinionated outlier removal (that's
-- what fct_used_car_listing.is_price_outlier is for, downstream).

with source as (
    select * from {{ source('raw', 'used_car_listings') }}
)

select
    id,
    region,
    state,
    price::double                          as price_usd,
    year::int                              as year,
    manufacturer,
    model,
    condition,
    cylinders,
    fuel,
    odometer::double                       as odometer_miles,
    title_status,
    transmission,
    drive,
    size,
    type                                   as vehicle_type,
    paint_color,
    lat::double                            as lat,
    long::double                           as long,
    has_vin,
    cast(posting_date as timestamp)::date  as posting_date

from source
where price::double > 0
  and year::int between 1900 and (date_part('year', current_date) + 1)
  and posting_date is not null
