import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv()

from db import bootstrap_database
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from validator import schema_match_check, llm_judge, compute_confidence

MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))

st.set_page_config(
    page_title="Secure Text-to-SQL",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    }

    .page-header {
        border-left: 3px solid #e63946;
        padding: 14px 0 14px 20px;
        margin-bottom: 28px;
    }
    .page-header h2 {
        margin: 0 0 4px 0;
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: -0.3px;
    }
    .page-header p {
        margin: 0;
        font-size: 0.84rem;
        opacity: 0.5;
    }

    .label {
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        opacity: 0.4;
        margin-bottom: 6px;
        margin-top: 20px;
    }

    .stButton > button {
        border-radius: 5px;
        font-size: 0.8rem;
        padding: 5px 14px;
        transition: border-color 0.15s, color 0.15s;
    }
    .stButton > button[kind="primary"] {
        background-color: #e63946;
        border: none;
        border-radius: 5px;
        font-weight: 600;
        font-size: 0.88rem;
        padding: 7px 28px;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #c1121f !important;
    }

    .stTextInput > div > div > input {
        border-radius: 5px;
        font-size: 0.93rem;
        padding: 9px 13px;
    }
    .stTextInput > div > div > input:focus {
        border-color: #00c8c8 !important;
        box-shadow: 0 0 0 2px rgba(0, 200, 200, 0.15) !important;
    }

    .explanation-card {
        border-left: 2px solid #00c8c8;
        padding: 10px 16px;
        border-radius: 0 5px 5px 0;
        margin: 8px 0 20px 0;
        opacity: 0.85;
    }
    .explanation-card p {
        margin: 0;
        font-size: 0.85rem;
        font-style: italic;
    }

    .badge {
        display: inline-block;
        border-radius: 4px;
        padding: 3px 12px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.5px;
    }
    .badge-high   { background: #0d2b1a; color: #00e676; border: 1px solid #00e676; }
    .badge-medium { background: #1f1a00; color: #ffd600; border: 1px solid #ffd600; }
    .badge-low    { background: #1f0007; color: #e63946; border: 1px solid #e63946; }

    .judge-text {
        font-size: 0.82rem;
        font-style: italic;
        opacity: 0.5;
        margin-top: 7px;
    }

    .row-tag {
        display: inline-block;
        border-radius: 4px;
        padding: 1px 9px;
        font-size: 0.72rem;
        opacity: 0.45;
        margin-left: 8px;
        font-weight: normal;
        letter-spacing: 0;
        text-transform: none;
        border: 1px solid currentColor;
    }

    .stDownloadButton > button {
        border-radius: 5px;
        font-size: 0.8rem;
        padding: 5px 14px;
    }

    .footer {
        text-align: center;
        font-size: 0.72rem;
        opacity: 0.3;
        padding-top: 6px;
    }

    #MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Cached resource functions — only run once per session ─────────────────────

@st.cache_resource
def get_demo_engine():
    bootstrap_database()
    from db import DB_PATH
    return create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)


@st.cache_resource
def get_url_engine(url: str):
    return create_engine(url, poolclass=NullPool)


@st.cache_resource
def get_file_engine(path: str, is_duckdb: bool):
    url = f"duckdb:///{path}" if is_duckdb else f"sqlite:///{path}"
    return create_engine(url, poolclass=NullPool)


@st.cache_data(ttl=120, show_spinner=False)
def load_schema(_engine):
    schema = get_schema_dict(_engine)
    return schema, schema_to_prompt_string(schema), all_known_identifiers(schema)


@st.cache_data(show_spinner=False)
def cached_generate_sql(question: str, schema_text: str):
    return generate_sql(question, schema_text)


@st.cache_data(show_spinner=False)
def cached_llm_judge(question: str, sql: str, sample: str):
    return llm_judge(question, sql, sample)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-header">
    <h2>Secure Text-to-SQL</h2>
    <p>Natural language to validated SQL — guardrails, schema checking, LLM confidence scoring</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("**Database source**")

db_source_type = st.sidebar.radio(
    "source",
    ["Demo Database (Chinook)", "Upload SQLite/DuckDB File", "Database Connection URL"],
    label_visibility="collapsed",
)

engine = None

if db_source_type == "Demo Database (Chinook)":
    try:
        engine = get_demo_engine()
        st.sidebar.success("Chinook demo database ready.")
    except Exception as e:
        st.sidebar.error(f"Failed: {e}")

elif db_source_type == "Upload SQLite/DuckDB File":
    uploaded_file = st.sidebar.file_uploader(
        "Upload .db / .sqlite / .duckdb",
        type=["db", "sqlite", "sqlite3", "duckdb"],
    )
    if uploaded_file is not None:
        upload_dir = "data/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        db_file_path = os.path.join(upload_dir, uploaded_file.name)
        with open(db_file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        try:
            engine = get_file_engine(db_file_path, is_duckdb=(ext == ".duckdb"))
            st.sidebar.success(f"Connected to {uploaded_file.name}")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")
    else:
        st.sidebar.info("Upload a file to begin.")

elif db_source_type == "Database Connection URL":
    env_url = os.getenv("DATABASE_URL") or ""
    conn_url = st.sidebar.text_input(
        "SQLAlchemy URL",
        value=env_url,
        placeholder="mysql+pymysql://user:pass@host:3306/db",
    )
    if conn_url:
        try:
            engine = get_url_engine(conn_url)
            with engine.connect():
                pass
            st.sidebar.success("Connected.")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")
    else:
        st.sidebar.info("Enter a connection string to begin.")

st.sidebar.divider()
st.sidebar.caption(
    f"Queries are guardrail-checked, schema-validated, "
    f"and capped at {MAX_ROWS} rows before execution."
)


# ── Schema ────────────────────────────────────────────────────────────────────
if engine is None:
    st.warning("Select a database source from the sidebar to get started.")
    st.stop()

try:
    schema, schema_text, known_ids = load_schema(engine)
except Exception as e:
    st.error(f"Could not read database schema: {e}")
    st.stop()

with st.expander("Active schema", expanded=False):
    st.code(schema_text, language="text")


# ── Session state ─────────────────────────────────────────────────────────────
if "user_query" not in st.session_state:
    st.session_state.user_query = ""
if "auto_run" not in st.session_state:
    st.session_state.auto_run = False


# ── Quick queries ─────────────────────────────────────────────────────────────
st.markdown('<div class="label">Quick queries</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns([1, 1.2, 1.4, 1])
if c1.button("All artists"):
    st.session_state.user_query = "Show all artists"
    st.session_state.auto_run = True
if c2.button("AC/DC tracks"):
    st.session_state.user_query = "List all tracks belonging to AC/DC"
    st.session_state.auto_run = True
if c3.button("Top spending customers"):
    st.session_state.user_query = "Which customers spent the most in total?"
    st.session_state.auto_run = True
if c4.button("Test guardrail"):
    st.session_state.user_query = "Drop the artists table"
    st.session_state.auto_run = True


# ── Question input ────────────────────────────────────────────────────────────
st.markdown('<div class="label">Question</div>', unsafe_allow_html=True)

question = st.text_input(
    "question",
    value=st.session_state.user_query,
    placeholder="e.g. Which country's customers spent the most?",
    label_visibility="collapsed",
)

run = st.button("Run Query", type="primary")

# consume auto_run flag
should_run = run or st.session_state.auto_run
if st.session_state.auto_run:
    st.session_state.auto_run = False


# ── Pipeline ──────────────────────────────────────────────────────────────────
if should_run and question:

    with st.spinner("Generating SQL..."):
        try:
            result = cached_generate_sql(question, schema_text)
            sql = result["sql"]
            explanation = result["explanation"]
        except Exception as e:
            st.error(f"SQL generation failed: {e}")
            st.stop()

    st.markdown('<div class="label">Generated SQL</div>', unsafe_allow_html=True)
    st.code(sql, language="sql")
    st.markdown(
        f'<div class="explanation-card"><p>{explanation}</p></div>',
        unsafe_allow_html=True,
    )

    try:
        check_sql_is_safe(sql)
        safe_sql = enforce_row_limit(sql, MAX_ROWS)
    except GuardrailViolation as e:
        st.error(f"Guardrail blocked this query: {e}")
        st.stop()

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(safe_sql), conn)
    except Exception as e:
        st.error(f"Execution failed: {e}")
        st.stop()

    row_word = "row" if len(df) == 1 else "rows"
    st.markdown(
        f'<div class="label">Results <span class="row-tag">{len(df)} {row_word}</span></div>',
        unsafe_allow_html=True,
    )
    st.dataframe(df, width="stretch")

    if not df.empty:
        st.download_button(
            label="Download CSV",
            data=df.to_csv(index=False),
            file_name="results.csv",
            mime="text/csv",
        )

    with st.spinner("Validating..."):
        schema_ok, unknown_tokens = schema_match_check(sql, known_ids)
        sample = df.head(5).to_string(index=False) if not df.empty else "(no rows)"
        judge = cached_llm_judge(question, sql, sample)
        confidence = compute_confidence(schema_ok, judge["score"])

    badge_class = {
        "High": "badge-high",
        "Medium": "badge-medium",
        "Low": "badge-low",
    }[confidence]

    st.markdown(f"""
    <div style="margin-top:18px;">
        <div class="label" style="margin-top:0;">Confidence</div>
        <span class="badge {badge_class}">{confidence}</span>
        <div class="judge-text">{judge['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    if not schema_ok:
        st.warning(f"Unrecognized schema tokens: {unknown_tokens}")

st.divider()
st.markdown(
    f'<div class="footer">SELECT-only &middot; {MAX_ROWS}-row limit &middot; schema-validated &middot; LLM-judged</div>',
    unsafe_allow_html=True,
)
