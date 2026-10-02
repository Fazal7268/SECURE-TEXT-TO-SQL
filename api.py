import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from audit import init_db, log_query, get_history
from db import bootstrap_database, DB_PATH
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from validator import schema_match_check, llm_judge, compute_confidence

load_dotenv()

limiter = Limiter(key_func=get_remote_address)


class ErrorResponse(BaseModel):
    detail: str

app = FastAPI(
    title="Secure Text-to-SQL API",
    description="Natural language to SQL with guardrails. POST a question, get back validated SQL and results.",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

bootstrap_database()
init_db()


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    row_count: int
    columns: list[str]
    rows: list[dict]
    schema_check_passed: bool
    judge_score: int
    judge_reason: str
    confidence: str


@app.get("/")
def root():
    return {"message": "Secure Text-to-SQL API is running. See /docs for usage."}


@app.get("/schema", summary="Returns the current database schema")
def get_schema():
    engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
    schema = get_schema_dict(engine)
    if not schema:
        raise HTTPException(status_code=404, detail="No tables found in the database.")
    return schema


@app.get("/history", summary="Returns recent query audit log")
def history(
    limit: int = Query(50, ge=1, le=500),
    status: str = Query("all", pattern="^(all|passed|blocked)$"),
):
    blocked_only = status == "blocked"
    passed_only = status == "passed"
    rows = get_history(limit=limit, blocked_only=blocked_only)
    if passed_only:
        rows = [r for r in rows if not r["blocked"]]
    return rows


@app.post(
    "/query",
    response_model=QueryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Empty question"},
        403: {"model": ErrorResponse, "description": "Guardrail blocked the query"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Query execution failed"},
    },
)
@limiter.limit("5/minute")
def run_query(request: Request, body: QueryRequest):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
    schema = get_schema_dict(engine)
    schema_text = schema_to_prompt_string(schema)
    known_ids = all_known_identifiers(schema)

    try:
        result = generate_sql(question, schema_text)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM failed to generate SQL: {e}")

    sql = result["sql"]
    explanation = result["explanation"]

    try:
        check_sql_is_safe(sql)
    except GuardrailViolation as e:
        log_query(question, sql=sql, blocked=True, blocked_reason=str(e))
        raise HTTPException(status_code=403, detail=str(e))

    sql = enforce_row_limit(sql, max_rows=500)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")

    schema_passed, unknown_tokens = schema_match_check(sql, known_ids)
    result_sample = df.head(5).to_string(index=False) if not df.empty else "(no rows)"
    judge = llm_judge(question, sql, result_sample)
    confidence = compute_confidence(schema_passed, judge["score"])

    log_query(
        question,
        sql=sql,
        confidence=confidence,
        judge_score=judge["score"],
        row_count=len(df),
    )

    return QueryResponse(
        question=question,
        sql=sql,
        explanation=explanation,
        row_count=len(df),
        columns=df.columns.tolist(),
        rows=df.head(100).to_dict(orient="records"),
        schema_check_passed=schema_passed,
        judge_score=judge["score"],
        judge_reason=judge["reason"],
        confidence=confidence,
    )
