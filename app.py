import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv()

from db import bootstrap_database, DB_PATH
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from validator import schema_match_check, llm_judge, compute_confidence

MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))

st.set_page_config(page_title="Text-to-SQL Interface", layout="wide")
st.title("Natural Language to SQL with Guardrails")
st.caption("Translate English to SQL safely, with schema validation and automated correctness checks.")

bootstrap_database()
engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
schema = get_schema_dict(engine)
schema_text = schema_to_prompt_string(schema)
known_ids = all_known_identifiers(schema)

with st.expander("Active Database Schema"):
    st.code(schema_text, language="text")

question = st.text_input("Query", placeholder="e.g. Which country's customers spent the most in total?")

if st.button("Run Query", type="primary") and question:
    with st.spinner("Generating query..."):
        try:
            result = generate_sql(question, schema_text)
            sql = result["sql"]
            explanation = result["explanation"]
        except Exception as e:
            st.error(f"SQL generation failed: {e}")
            st.stop()

    st.subheader("Generated SQL")
    st.code(sql, language="sql")
    st.caption(explanation)

    try:
        check_sql_is_safe(sql)
        safe_sql = enforce_row_limit(sql, MAX_ROWS)
    except GuardrailViolation as e:
        st.error(f"Guardrail blocked query: {e}")
        st.stop()

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(safe_sql), conn)
    except Exception as e:
        st.error(f"SQL execution error: {e}")
        st.stop()

    st.subheader("Query Results")
    st.dataframe(df)

    with st.spinner("Validating results..."):
        schema_ok, unknown_tokens = schema_match_check(sql, known_ids)
        sample = df.head(5).to_string(index=False) if not df.empty else "(no rows returned)"
        judge = llm_judge(question, sql, sample)
        confidence = compute_confidence(schema_ok, judge["score"])

    badge_color = {"High": "green", "Medium": "orange", "Low": "red"}[confidence]
    st.markdown(f"**Confidence:** :{badge_color}[{confidence}]  \n*{judge['reason']}*")
