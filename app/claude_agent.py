"""The chat "SQL analyst": a manual Claude tool-use loop with one tool
(run_sql) so a natural-language question gets answered by querying the wide
mart directly, instead of a fixed dashboard. Manual loop (not the SDK's
beta tool runner) because the UI needs the exact SQL each turn ran, per
turn, to show in an expander — see app/streamlit_app.py.

Model defaults to claude-opus-5 (Anthropic's guidance: don't downgrade for
cost by default). Override ANTHROPIC_MODEL in .env for a cheaper/faster
demo, e.g. claude-sonnet-5 or claude-haiku-4-5.
"""
import json
import os

import anthropic
from dotenv import load_dotenv

from app.schema_context import build_schema_context
from app.sql_tool import RUN_SQL_TOOL, run_sql

load_dotenv()

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT_TEMPLATE = """You are a data analyst answering questions about a wide, denormalized used-car listings table via the run_sql tool (DuckDB SQL).

This table is deliberately wide instead of star-schemed: every column an analyst might filter or group by lives on the one row, so most questions can be answered with a single SELECT against main_marts.fct_used_car_listing — no joins needed.

Schema:
{schema}

Rules:
- Only SELECT/WITH queries — run_sql rejects anything else.
- price_usd is the raw USD listing price. price_mxn_inflation_adjusted is the Banxico-driven, inflation-adjusted MXN price restated in today's pesos — prefer it whenever a question is about value in pesos, and flag it in your answer if any involved rows have is_fx_fallback_data = true (the FX/inflation numbers for those rows are a rough placeholder, not real historical data).
- Answer with a direct, numbers-forward sentence or two, not just a raw table dump — the SQL and results are shown separately in the UI.
"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _model() -> str:
    return os.getenv("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL


def ask(question: str, history: list[dict] | None = None) -> dict:
    """Runs the tool-use loop for one user question.

    `history` is the prior conversation in Claude Messages API format
    (NOT including this question) — pass session state to keep multi-turn
    context; omit for a fresh conversation.

    Returns {"answer": str, "queries": [{"sql", "row_count", "error"}, ...],
    "messages": <updated history to store back in session state>}.
    """
    client = _client()
    messages = list(history or [])
    messages.append({"role": "user", "content": question})

    executed_queries: list[dict] = []
    system = SYSTEM_PROMPT_TEMPLATE.format(schema=build_schema_context())

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=_model(),
            max_tokens=MAX_TOKENS,
            system=system,
            tools=[RUN_SQL_TOOL],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text")
            return {"answer": answer, "queries": executed_queries, "messages": messages}

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            sql = block.input.get("sql", "")
            try:
                rows = run_sql(sql)
                executed_queries.append({"sql": sql, "row_count": len(rows), "error": None})
                content = json.dumps(rows, default=str)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content}
                )
            except Exception as exc:  # noqa: BLE001 — surfaced to Claude as a tool error, not raised
                executed_queries.append({"sql": sql, "row_count": 0, "error": str(exc)})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return {
        "answer": (
            "I wasn't able to finish within the tool-call limit for this turn — "
            "try a narrower question."
        ),
        "queries": executed_queries,
        "messages": messages,
    }
