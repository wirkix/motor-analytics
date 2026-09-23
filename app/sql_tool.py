"""The one tool the Claude agent gets: run a read-only SELECT against the
wide mart. Defense in depth, in order of what actually stops something bad:
  1. The DuckDB connection itself is opened read_only=True — a write fails
     at the file-lock level no matter what SQL gets past the checks below.
  2. A keyword guard rejects anything that isn't a SELECT/WITH, or that
     contains a write/DDL/PRAGMA keyword anywhere in the query.
  3. External access is disabled on the connection (and the setting is
     locked), so SELECT-shaped file/network readers -- read_text('.env'),
     read_csv('C:/...'), 'https://...' -- fail with a PermissionException.
     read_only=True alone does NOT stop these: it only blocks writes to the
     database file, and none of those function names trip the keyword guard.
  4. A LIMIT is auto-appended if the query doesn't have one, so a broad
     question can't return the whole table into the chat.
"""
import re

import duckdb

from ingest.config import DUCKDB_PATH

MAX_ROWS = 200

_ALLOWED_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_FORBIDDEN_KEYWORD = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|copy|export|create|"
    r"pragma|call|vacuum|checkpoint|install|load)\b",
    re.IGNORECASE,
)

RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run a read-only SQL SELECT query (DuckDB dialect) against "
        "main_marts.fct_used_car_listing and return the resulting rows as "
        "a list of objects. Only SELECT/WITH statements are allowed — "
        "writes, DDL, and PRAGMA are rejected. Results are capped at "
        f"{MAX_ROWS} rows; a LIMIT is added automatically if you don't "
        "include one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A SELECT/WITH query against main_marts.fct_used_car_listing.",
            },
        },
        "required": ["sql"],
    },
}


def _guard(sql: str) -> None:
    if not _ALLOWED_PREFIX.match(sql):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    if _FORBIDDEN_KEYWORD.search(sql):
        raise ValueError("Query contains a disallowed keyword (writes/DDL/PRAGMA are blocked).")


def _with_limit(sql: str) -> str:
    if re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip().rstrip(';')}\nlimit {MAX_ROWS}"


def run_sql(sql: str) -> list[dict]:
    _guard(sql)
    sql = _with_limit(sql)
    con = duckdb.connect(
        str(DUCKDB_PATH),
        read_only=True,
        config={"enable_external_access": False, "lock_configuration": True},
    )
    try:
        result = con.execute(sql)
        columns = [d[0] for d in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        con.close()
