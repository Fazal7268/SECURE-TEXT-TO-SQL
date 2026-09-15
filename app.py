import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv()

from db import get_engine, bootstrap_database
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from validator import schema_match_check, llm_judge, compute_confidence

MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))

st.set_page_config(page_title="Text-to-SQL Interface", layout="wide")
st.title("Natural Language to SQL with Guardrails")
st.caption("Translate English to SQL safely, with schema validation and automated correctness checks.")

# Sidebar database configuration
st.sidebar.header("Database Source")
db_source_type = st.sidebar.radio(
    "Select Source",
    ["Demo Database (Chinook)", "Upload SQLite/DuckDB File", "Database Connection URL"]
)

engine = None
schema_text = ""
known_ids = set()

if db_source_type == "Demo Database (Chinook)":
    try:
        bootstrap_database()
        from db import DB_PATH
        engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
        st.sidebar.success("Loaded Chinook demo database.")
    except Exception as e:
        st.sidebar.error(f"Error loading demo database: {e}")

elif db_source_type == "Upload SQLite/DuckDB File":
    uploaded_file = st.sidebar.file_uploader(
        "Upload a SQLite (.db, .sqlite, .sqlite3) or DuckDB (.duckdb) file", 
        type=["db", "sqlite", "sqlite3", "duckdb"]
    )
    if uploaded_file is not None:
        upload_dir = "data/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        db_file_path = os.path.join(upload_dir, uploaded_file.name)

        with open(db_file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        db_url = f"duckdb:///{db_file_path}" if ext == ".duckdb" else f"sqlite:///{db_file_path}"

        try:
            engine = create_engine(db_url, poolclass=NullPool)
            with engine.connect() as conn:
                pass
            st.sidebar.success(f"Connected to {uploaded_file.name}")
        except Exception as e:
            st.sidebar.error(f"Database connection failed: {e}")
            engine = None
    else:
        st.sidebar.info("Upload a database file to get started.")

elif db_source_type == "Database Connection URL":
    env_conn_url = os.getenv("DATABASE_URL") or ""
    conn_url = st.sidebar.text_input(
        "SQLAlchemy Connection URL", 
        value=env_conn_url,
        placeholder="mysql+pymysql://user:pass@host:3306/db"
    )
    if conn_url:
        try:
            engine = create_engine(conn_url, poolclass=NullPool)
            with engine.connect() as conn:
                pass
            st.sidebar.success("Connected to database server.")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")
            engine = None
    else:
        st.sidebar.info("Enter a connection string to begin.")

# Extract schema from whichever database is active
if engine is not None:
    try:
        schema = get_schema_dict(engine)
        schema_text = schema_to_prompt_string(schema)
        known_ids = all_known_identifiers(schema)
    except Exception as e:
        st.error(f"Failed to inspect database schema: {e}")
        st.stop()
else:
    st.warning("Connect or upload a database in the sidebar to start asking questions.")
    st.stop()

with st.expander("Active Database Schema"):
    st.code(schema_text, language="text")

question = st.text_input(
    "Query",
    placeholder="e.g. Which country's customers spent the most in total?",
)

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

    # Run query through safety guardrails before execution
    try:
        check_sql_is_safe(sql)
        safe_sql = enforce_row_limit(sql, MAX_ROWS)
    except GuardrailViolation as e:
        st.error(f"Guardrail blocked query: {e}")
        st.stop()

    # Execute against active database
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(safe_sql), conn)
    except Exception as e:
        st.error(f"SQL execution error: {e}")
        st.stop()

    st.subheader("Query Results")
    st.dataframe(df)

    if not df.empty:
        st.download_button(
            label="Download as CSV",
            data=df.to_csv(index=False),
            file_name="query_results.csv",
            mime="text/csv",
        )

    # Validate output to detect hallucinations
    with st.spinner("Validating results..."):
        schema_ok, unknown_tokens = schema_match_check(sql, known_ids)
        sample = df.head(5).to_string(index=False) if not df.empty else "(no rows returned)"
        judge = llm_judge(question, sql, sample)
        confidence = compute_confidence(schema_ok, judge["score"])

    badge_color = {"High": "green", "Medium": "orange", "Low": "red"}[confidence]
    st.markdown(f"**Confidence:** :{badge_color}[{confidence}]  \n*{judge['reason']}*")

    if not schema_ok:
        st.warning(f"Unrecognized schema tokens detected: {unknown_tokens}")

st.divider()
st.caption(
    f"Safety guardrails enforce SELECT-only queries and a {MAX_ROWS}-row cap. "
    "Confidence score evaluates schema accuracy and semantic correctness."
)
