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

st.set_page_config(
    page_title="Secure Text-to-SQL",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Base */
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }

    .stApp {
        background-color: #0a0a0a;
        color: #e0e0e0;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #111111;
        border-right: 1px solid #1e1e1e;
    }

    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span {
        color: #c0c0c0 !important;
    }

    /* Header strip */
    .header-strip {
        background: linear-gradient(90deg, #1a0000 0%, #0a0a0a 60%);
        border-left: 4px solid #e63946;
        padding: 18px 24px 12px 24px;
        margin-bottom: 24px;
        border-radius: 0 6px 6px 0;
    }

    .header-strip h1 {
        color: #ffffff;
        font-size: 1.6rem;
        font-weight: 700;
        margin: 0 0 4px 0;
        letter-spacing: -0.3px;
    }

    .header-strip p {
        color: #888;
        font-size: 0.85rem;
        margin: 0;
    }

    /* Quick query buttons */
    .stButton > button {
        background-color: #141414;
        color: #00e5e5;
        border: 1px solid #1e3a3a;
        border-radius: 6px;
        font-size: 0.8rem;
        padding: 6px 14px;
        transition: all 0.15s ease;
    }

    .stButton > button:hover {
        background-color: #0d2b2b;
        border-color: #00e5e5;
        color: #ffffff;
    }

    /* Primary run button */
    .stButton > button[kind="primary"] {
        background-color: #e63946;
        color: #ffffff;
        border: none;
        font-weight: 600;
        font-size: 0.9rem;
        padding: 8px 28px;
        border-radius: 6px;
    }

    .stButton > button[kind="primary"]:hover {
        background-color: #c1121f;
    }

    /* Text input */
    .stTextInput > div > div > input {
        background-color: #111111;
        color: #e0e0e0;
        border: 1px solid #2a2a2a;
        border-radius: 6px;
        font-size: 0.95rem;
        padding: 10px 14px;
    }

    .stTextInput > div > div > input:focus {
        border-color: #00e5e5;
        box-shadow: 0 0 0 2px rgba(0, 229, 229, 0.12);
    }

    /* Code blocks */
    .stCode {
        background-color: #0f0f0f !important;
        border: 1px solid #1e1e1e;
        border-radius: 6px;
    }

    /* Dataframe */
    .stDataFrame {
        border: 1px solid #1e1e1e;
        border-radius: 6px;
        overflow: hidden;
    }

    /* Expander */
    .streamlit-expanderHeader {
        background-color: #111111;
        color: #888 !important;
        border: 1px solid #1e1e1e;
        border-radius: 6px;
        font-size: 0.82rem;
    }

    /* Section labels */
    .section-label {
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        color: #555;
        margin-bottom: 6px;
    }

    /* SQL result card */
    .result-card {
        background-color: #0f0f0f;
        border: 1px solid #1e1e1e;
        border-left: 3px solid #00e5e5;
        border-radius: 0 6px 6px 0;
        padding: 14px 18px;
        margin: 10px 0 16px 0;
    }

    .result-card p {
        color: #888;
        font-size: 0.87rem;
        margin: 0;
        font-style: italic;
    }

    /* Confidence badge */
    .conf-high {
        display: inline-block;
        background: #0d2b1a;
        color: #00e676;
        border: 1px solid #00e676;
        border-radius: 4px;
        padding: 2px 10px;
        font-size: 0.8rem;
        font-weight: 600;
    }

    .conf-medium {
        display: inline-block;
        background: #1f1a00;
        color: #ffd600;
        border: 1px solid #ffd600;
        border-radius: 4px;
        padding: 2px 10px;
        font-size: 0.8rem;
        font-weight: 600;
    }

    .conf-low {
        display: inline-block;
        background: #1f0007;
        color: #e63946;
        border: 1px solid #e63946;
        border-radius: 4px;
        padding: 2px 10px;
        font-size: 0.8rem;
        font-weight: 600;
    }

    .judge-reason {
        color: #666;
        font-size: 0.83rem;
        margin-top: 6px;
        font-style: italic;
    }

    /* Divider */
    hr {
        border-color: #1a1a1a !important;
        margin: 28px 0 !important;
    }

    /* Footer */
    .footer-note {
        color: #3a3a3a;
        font-size: 0.75rem;
        text-align: center;
        padding-top: 8px;
    }

    /* Hide streamlit default decorations */
    #MainMenu, footer, header {visibility: hidden;}

    /* Sidebar brand */
    .sidebar-brand {
        color: #e63946;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: 0.5px;
        margin-bottom: 20px;
    }

    /* Download button */
    .stDownloadButton > button {
        background-color: #111111;
        color: #00e5e5;
        border: 1px solid #1e3a3a;
        border-radius: 6px;
        font-size: 0.82rem;
    }

    .stDownloadButton > button:hover {
        background-color: #0d2b2b;
        border-color: #00e5e5;
    }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-strip">
    <h1>🛡️ Secure Text-to-SQL</h1>
    <p>Natural language → validated SQL with guardrails and confidence scoring</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown('<div class="sidebar-brand">⚡ Database Source</div>', unsafe_allow_html=True)

db_source_type = st.sidebar.radio(
    "Select source",
    ["Demo Database (Chinook)", "Upload SQLite/DuckDB File", "Database Connection URL"],
    label_visibility="collapsed",
)

engine = None
schema_text = ""
known_ids = set()

if db_source_type == "Demo Database (Chinook)":
    try:
        bootstrap_database()
        from db import DB_PATH
        engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
        st.sidebar.success("Chinook demo database loaded.")
    except Exception as e:
        st.sidebar.error(f"Error: {e}")

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
        db_url = f"duckdb:///{db_file_path}" if ext == ".duckdb" else f"sqlite:///{db_file_path}"
        try:
            engine = create_engine(db_url, poolclass=NullPool)
            with engine.connect():
                pass
            st.sidebar.success(f"Connected to {uploaded_file.name}")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")
            engine = None
    else:
        st.sidebar.info("Upload a file to get started.")

elif db_source_type == "Database Connection URL":
    env_conn_url = os.getenv("DATABASE_URL") or ""
    conn_url = st.sidebar.text_input(
        "SQLAlchemy URL",
        value=env_conn_url,
        placeholder="mysql+pymysql://user:pass@host:3306/db",
    )
    if conn_url:
        try:
            engine = create_engine(conn_url, poolclass=NullPool)
            with engine.connect():
                pass
            st.sidebar.success("Connected.")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")
            engine = None
    else:
        st.sidebar.info("Enter a connection string to begin.")

st.sidebar.divider()
st.sidebar.markdown('<div class="section-label">About</div>', unsafe_allow_html=True)
st.sidebar.caption("Powered by Gemini LLM. Queries are validated against schema and judged for semantic correctness before results are returned.")


# ── Schema ────────────────────────────────────────────────────────────────────
if engine is not None:
    try:
        schema = get_schema_dict(engine)
        schema_text = schema_to_prompt_string(schema)
        known_ids = all_known_identifiers(schema)
    except Exception as e:
        st.error(f"Failed to read database schema: {e}")
        st.stop()
else:
    st.warning("Connect a database from the sidebar to start.")
    st.stop()

with st.expander("View active schema", expanded=False):
    st.code(schema_text, language="text")


# ── Query Input ───────────────────────────────────────────────────────────────
st.markdown('<div class="section-label" style="margin-top:8px;">Quick queries</div>', unsafe_allow_html=True)

if "user_query" not in st.session_state:
    st.session_state.user_query = ""

col1, col2, col3, col4 = st.columns([1, 1.3, 1.1, 1])
if col1.button("All artists"):
    st.session_state.user_query = "Show all artists"
if col2.button("AC/DC tracks"):
    st.session_state.user_query = "List all tracks belonging to AC/DC"
if col3.button("Top spending customers"):
    st.session_state.user_query = "Which customers spent the most in total?"
if col4.button("Test guardrail"):
    st.session_state.user_query = "Drop the artists table"

st.markdown('<div class="section-label" style="margin-top:16px;">Your question</div>', unsafe_allow_html=True)

question = st.text_input(
    "question",
    value=st.session_state.user_query,
    placeholder="e.g. Which country's customers spent the most in total?",
    label_visibility="collapsed",
)

run = st.button("Run Query", type="primary")


# ── Pipeline ──────────────────────────────────────────────────────────────────
if run and question:
    with st.spinner("Generating SQL..."):
        try:
            result = generate_sql(question, schema_text)
            sql = result["sql"]
            explanation = result["explanation"]
        except Exception as e:
            st.error(f"SQL generation failed: {e}")
            st.stop()

    st.markdown('<div class="section-label" style="margin-top:20px;">Generated SQL</div>', unsafe_allow_html=True)
    st.code(sql, language="sql")
    st.markdown(f'<div class="result-card"><p>{explanation}</p></div>', unsafe_allow_html=True)

    try:
        check_sql_is_safe(sql)
        safe_sql = enforce_row_limit(sql, MAX_ROWS)
    except GuardrailViolation as e:
        st.error(f"🚫 Guardrail blocked this query: {e}")
        st.stop()

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(safe_sql), conn)
    except Exception as e:
        st.error(f"Execution error: {e}")
        st.stop()

    st.markdown(f'<div class="section-label" style="margin-top:20px;">Results — {len(df)} row{"s" if len(df) != 1 else ""}</div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        st.download_button(
            label="⬇ Download CSV",
            data=df.to_csv(index=False),
            file_name="query_results.csv",
            mime="text/csv",
        )

    with st.spinner("Validating..."):
        schema_ok, unknown_tokens = schema_match_check(sql, known_ids)
        sample = df.head(5).to_string(index=False) if not df.empty else "(no rows)"
        judge = llm_judge(question, sql, sample)
        confidence = compute_confidence(schema_ok, judge["score"])

    badge_class = {"High": "conf-high", "Medium": "conf-medium", "Low": "conf-low"}[confidence]
    st.markdown(f"""
    <div style="margin-top:16px;">
        <span class="section-label">Confidence</span><br/>
        <span class="{badge_class}">{confidence}</span>
        <div class="judge-reason">{judge['reason']}</div>
    </div>
    """, unsafe_allow_html=True)

    if not schema_ok:
        st.warning(f"Unknown schema tokens detected: {unknown_tokens}")

st.divider()
st.markdown(
    f'<div class="footer-note">SELECT-only · {MAX_ROWS}-row cap · schema-validated · LLM-judged</div>',
    unsafe_allow_html=True,
)
