"""Streamlit chat over the wide mart, answered live by Claude (app/claude_agent.py).

Run: streamlit run app/streamlit_app.py
"""
import os

import streamlit as st

# Streamlit Community Cloud injects deploy-time secrets via st.secrets, not
# the OS environment — app/claude_agent.py (and python-dotenv locally) reads
# plain env vars, so bridge the two here rather than touching that module.
# st.secrets raises StreamlitSecretNotFoundError when no secrets.toml exists
# anywhere (true for local dev, which uses .env instead) — that's expected,
# not an error.
try:
    for _key in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "BANXICO_TOKEN"):
        if _key in st.secrets and not os.getenv(_key):
            os.environ[_key] = st.secrets[_key]
except st.errors.StreamlitSecretNotFoundError:
    pass

from app.claude_agent import ask

st.set_page_config(page_title="Motor Analytics", page_icon="\U0001f697")

st.title("Motor Analytics")
st.caption(
    "Ask questions in plain language — Claude writes and runs the SQL against "
    "the wide `fct_used_car_listing` table itself, live. No fixed dashboard."
)

SAMPLE_QUESTIONS = [
    "What are the 5 most expensive luxury SUVs listed in Texas?",
    "What's the average inflation-adjusted MXN price by brand tier?",
    "Which manufacturer has the highest average price per mile?",
    "How many listings are electric or hybrid, broken down by US region?",
]

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # Claude Messages API format
if "display_history" not in st.session_state:
    st.session_state.display_history = []  # [{role, text, queries}]
if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

with st.sidebar:
    st.subheader("Try asking")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True):
            st.session_state.pending_question = q


def render_queries(queries: list[dict]) -> None:
    if not queries:
        return
    label = f"SQL run ({len(queries)} quer{'y' if len(queries) == 1 else 'ies'})"
    with st.expander(label):
        for q in queries:
            st.code(q["sql"], language="sql")
            if q["error"]:
                st.error(q["error"])
            else:
                st.caption(f"{q['row_count']} row(s)")


for turn in st.session_state.display_history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["text"])
        render_queries(turn.get("queries", []))

typed_question = st.chat_input("Ask about the used-car listings...")
question = typed_question or st.session_state.pending_question
st.session_state.pending_question = None

if question:
    st.session_state.display_history.append({"role": "user", "text": question, "queries": []})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Querying..."):
            result = ask(question, history=st.session_state.chat_history)
        st.markdown(result["answer"])
        render_queries(result["queries"])

    st.session_state.chat_history = result["messages"]
    st.session_state.display_history.append(
        {"role": "assistant", "text": result["answer"], "queries": result["queries"]}
    )
