import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")

def _init_client():
    api_key = os.getenv("GEMINI_API_KEY")
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return genai.Client(api_key=api_key) if api_key else genai.Client()

client = _init_client()

class JudgeResponse(BaseModel):
    score: int
    reason: str

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]*")

# Common SQL syntax keywords we should ignore when checking for hallucinated identifiers
SQL_STOPWORDS = {
    "select", "from", "where", "join", "inner", "left", "right", "outer",
    "on", "group", "by", "order", "limit", "as", "and", "or", "not", "in",
    "is", "null", "count", "sum", "avg", "min", "max", "distinct", "having",
    "asc", "desc", "with", "case", "when", "then", "else", "end", "like",
    "between", "union", "all", "exists", "coalesce", "concat", "round",
    "date", "strftime", "now", "year", "month", "day",
}

def schema_match_check(sql: str, known_identifiers: set) -> tuple[bool, list]:
    """
    Validates that every table and column referenced in the query exists in the schema.
    Returns (passed, list_of_unknown_tokens).
    """
    # Strip string literals first so text like 'AC/DC' or 'USA' isn't split into tokens
    sql_clean = re.sub(r"'[^']*'", "", sql)

    # Find table names in schema to match aliases against (e.g. 'tracks AS t')
    known_tables = {x for x in known_identifiers if "." not in x}
    aliases = {}
    for table in known_tables:
        pattern = rf"\b{table}\b\s+(?:as\s+)?\b([a-z_][a-z0-9_]*)\b"
        for match in re.findall(pattern, sql_clean, re.IGNORECASE):
            if match.lower() not in SQL_STOPWORDS:
                aliases[match.lower()] = table.lower()

    # Capture output column aliases (e.g., 'SUM(...) AS total_revenue') so they aren't flagged
    as_aliases = {
        alias.lower()
        for alias in re.findall(r"\bas\s+\b([a-z_][a-z0-9_]*)\b", sql_clean, re.IGNORECASE)
    }

    tokens = {t.lower() for t in IDENTIFIER_RE.findall(sql_clean)}
    tokens -= SQL_STOPWORDS
    tokens -= as_aliases
    tokens = {t for t in tokens if not t.isdigit()}

    # Resolve alias-prefixed identifiers (e.g. 't.track_id' -> 'tracks.track_id')
    # TODO: expand alias resolution to handle CTEs and subquery scopes
    unknown = []
    for token in tokens:
        if "." in token:
            prefix, suffix = token.split(".", 1)
            resolved = f"{aliases[prefix]}.{suffix}" if prefix in aliases else token
        else:
            if token in aliases:
                continue
            resolved = token

        if resolved not in known_identifiers:
            unknown.append(token)

    return len(unknown) == 0, unknown

def llm_judge(question: str, sql: str, result_sample: str) -> dict:
    """Uses Gemini as an independent judge to evaluate whether the query answered the question."""
    prompt = f"""Question: {question}

Generated SQL:
{sql}

Sample output (first few rows):
{result_sample}

Rate on a scale of 1-5 how accurately this SQL query answers the question."""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=JudgeResponse,
            ),
        )
        parsed = json.loads(response.text)
        return {"score": int(parsed["score"]), "reason": parsed["reason"]}
    except Exception:
        # Fallback if evaluation fails or returns unexpected format
        return {"score": 3, "reason": "Judge response could not be parsed."}

def compute_confidence(schema_passed: bool, judge_score: int) -> str:
    """Combines deterministic schema check and semantic evaluation into a confidence badge."""
    if not schema_passed:
        return "Low"
    if judge_score >= 4:
        return "High"
    if judge_score == 3:
        return "Medium"
    return "Low"
