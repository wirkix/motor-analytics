"""Renders dbt's own schema.yml into the compact column-description block
the Claude agent gets in its system prompt. dbt's docs double as the
agent's schema knowledge this way — there's no separate schema description
to let drift out of sync with the model.
"""
from pathlib import Path

import yaml

SCHEMA_YML_PATH = (
    Path(__file__).resolve().parent.parent / "dbt" / "models" / "marts" / "schema.yml"
)


def build_schema_context() -> str:
    with open(SCHEMA_YML_PATH, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    model = spec["models"][0]
    lines = [f"Table: main_marts.{model['name']}", ""]
    for col in model["columns"]:
        name = col["name"]
        desc = (col.get("description") or "").strip()
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    return "\n".join(lines)
