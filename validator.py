import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
client = genai.Client()

class JudgeResponse(BaseModel):
    score: int
    reason: str

IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]*")

SQL_STOPWORDS = {
    "select", "from", "where", "join", "inner", "left", "right", "outer",
    "on", "group", "by", "order", "limit", "as", "and", "or", "not", "in",
    "is", "null", "count", "sum", "avg", "min", "max", "distinct", "having",
    "asc", "desc", "with", "case", "when", "then", "else", "end", "like",
    "between", "union", "all", "exists", "coalesce", "concat", "round",
    "date", "strftime", "now", "year", "month", "day",
}

def schema_match_check(sql: str, known_identifiers: set) -> tuple[bool, list]:
    """Checks if all tokens in the query exist in the database schema."""
    tokens = {t.lower() for t in IDENTIFIER_RE.findall(sql)}
    tokens -= SQL_STOPWORDS
    tokens = {t for t in tokens if not t.isdigit()}

    unknown = [t for t in tokens if t not in known_identifiers]
    return len(unknown) == 0, unknown

def llm_judge(question: str, sql: str, result_sample: str) -> dict:
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
        return {"score": 3, "reason": "Judge response could not be parsed."}

def compute_confidence(schema_passed: bool, judge_score: int) -> str:
    if not schema_passed:
        return "Low"
    if judge_score >= 4:
        return "High"
    if judge_score == 3:
        return "Medium"
    return "Low"
