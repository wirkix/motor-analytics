import pytest

from app.sql_tool import _guard, _with_limit, run_sql


@pytest.mark.parametrize(
    "sql",
    [
        "insert into main_marts.fct_used_car_listing values (1)",
        "update main_marts.fct_used_car_listing set price_usd = 0",
        "delete from main_marts.fct_used_car_listing",
        "drop table main_marts.fct_used_car_listing",
        "alter table main_marts.fct_used_car_listing add column x int",
        "attach 'other.duckdb' as other",
        "copy main_marts.fct_used_car_listing to 'out.csv'",
        "pragma database_list",
        "create table evil as select 1",
        "select 1; drop table main_marts.fct_used_car_listing",
    ],
)
def test_guard_rejects_writes_and_ddl(sql):
    with pytest.raises(ValueError):
        _guard(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from main_marts.fct_used_car_listing",
        "with x as (select 1) select * from x",
        "SELECT count(*) FROM main_marts.fct_used_car_listing",
    ],
)
def test_guard_allows_select_and_with(sql):
    _guard(sql)  # should not raise


def test_with_limit_appends_when_missing():
    out = _with_limit("select * from t")
    assert "limit 200" in out.lower()


def test_with_limit_leaves_existing_limit_alone():
    out = _with_limit("select * from t limit 5")
    assert out.lower().count("limit") == 1


def test_run_sql_executes_against_the_committed_duckdb_file():
    rows = run_sql("select count(*) as n from main_marts.fct_used_car_listing")
    assert rows[0]["n"] > 0


def test_run_sql_rejects_write_before_touching_the_database():
    with pytest.raises(ValueError):
        run_sql("delete from main_marts.fct_used_car_listing")
