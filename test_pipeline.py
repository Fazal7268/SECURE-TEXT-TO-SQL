# runs the core pipeline without streamlit — guardrails, llm, db, validator, confidence
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import pandas as pd

from db import bootstrap_database, DB_PATH
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from validator import schema_match_check, llm_judge, compute_confidence

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def run(label, fn):
    try:
        fn()
        print(f"  {PASS}  {label}")
        results.append((label, True))
    except Exception as e:
        print(f"  {FAIL}  {label}")
        print(f"         {e}")
        results.append((label, False))


print("\n── Setup ────────────────────────────────────────")
bootstrap_database()
engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
schema = get_schema_dict(engine)
schema_text = schema_to_prompt_string(schema)
known_ids = all_known_identifiers(schema)
print(f"  Schema loaded — {len(schema)} table(s): {list(schema.keys())[:5]}")

print("\n── Test 1: Guardrails ───────────────────────────")

def test_select_passes():
    check_sql_is_safe("SELECT * FROM Artist")

def test_drop_blocked():
    try:
        check_sql_is_safe("DROP TABLE Artist")
        raise AssertionError("Should have raised GuardrailViolation")
    except GuardrailViolation:
        pass

def test_delete_blocked():
    try:
        check_sql_is_safe("DELETE FROM Artist WHERE ArtistId = 1")
        raise AssertionError("Should have raised GuardrailViolation")
    except GuardrailViolation:
        pass

def test_truncate_blocked():
    try:
        check_sql_is_safe("TRUNCATE TABLE Artist")
        raise AssertionError("Should have raised GuardrailViolation")
    except GuardrailViolation:
        pass

def test_row_limit_added():
    sql = enforce_row_limit("SELECT * FROM Artist", 200)
    assert "LIMIT" in sql.upper(), f"Expected LIMIT in: {sql}"

def test_row_limit_not_doubled():
    sql = enforce_row_limit("SELECT * FROM Artist LIMIT 10", 200)
    assert sql.upper().count("LIMIT") == 1, "LIMIT duplicated"

run("SELECT passes guardrail", test_select_passes)
run("DROP is blocked", test_drop_blocked)
run("DELETE is blocked", test_delete_blocked)
run("TRUNCATE is blocked", test_truncate_blocked)
run("Row limit appended when missing", test_row_limit_added)
run("Row limit not doubled if already present", test_row_limit_not_doubled)

print("\n── Test 2: LLM SQL Generation ───────────────────")

sql_result = None

def test_generate_sql():
    global sql_result
    sql_result = generate_sql("show all artists", schema_text)
    assert "sql" in sql_result and sql_result["sql"].strip(), "Empty SQL returned"
    assert "explanation" in sql_result, "Missing explanation"
    assert "SELECT" in sql_result["sql"].upper(), "Expected SELECT query"

def test_generated_sql_is_safe():
    assert sql_result is not None, "sql_result not set"
    check_sql_is_safe(sql_result["sql"])

run("LLM generates valid SQL", test_generate_sql)
run("Generated SQL passes guardrail", test_generated_sql_is_safe)

print("\n── Test 3: DB Execution ─────────────────────────")

df_result = None

def test_query_executes():
    global df_result
    assert sql_result is not None
    safe_sql = enforce_row_limit(sql_result["sql"], 200)
    with engine.connect() as conn:
        df_result = pd.read_sql(text(safe_sql), conn)
    assert df_result is not None and not df_result.empty, "Query returned no rows"
    print(f"         → {len(df_result)} rows, columns: {list(df_result.columns)}")

def test_direct_query():
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM artists LIMIT 5"), conn)
    assert not df.empty, "Expected at least one artist row"

run("Generated SQL executes against DuckDB", test_query_executes)
run("Direct SQL executes correctly", test_direct_query)

print("\n── Test 4: Schema Validator ─────────────────────")

def test_schema_match_valid():
    ok, unknown = schema_match_check("SELECT name FROM artists", known_ids)
    assert ok, f"Expected schema match to pass, unknown: {unknown}"

def test_schema_match_fake_table():
    ok, unknown = schema_match_check("SELECT foo FROM nonexistent_table", known_ids)
    assert not ok, "Expected schema match to fail for fake table"

run("Valid SQL passes schema check", test_schema_match_valid)
run("Fake table fails schema check", test_schema_match_fake_table)

print("\n── Test 5: LLM Judge + Confidence ───────────────")

def test_llm_judge():
    assert df_result is not None
    sample = df_result.head(5).to_string(index=False)
    judge = llm_judge("show all artists", sql_result["sql"], sample)
    assert "score" in judge and isinstance(judge["score"], int), "Bad judge response"
    assert "reason" in judge and judge["reason"], "Missing reason"
    assert 0 <= judge["score"] <= 10, f"Score out of range: {judge['score']}"
    print(f"         → score={judge['score']}, reason={judge['reason'][:60]}...")

def test_confidence_levels():
    assert compute_confidence(True, 9) == "High"
    assert compute_confidence(False, 3) == "Low"
    assert compute_confidence(True, 1) in ("Low", "Medium")  # low score → not High

run("LLM judge returns valid score", test_llm_judge)
run("Confidence levels map correctly", test_confidence_levels)

print("\n── Summary ──────────────────────────────────────")
passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"  {passed}/{total} tests passed")
if passed < total:
    print("\n  Failed:")
    for label, ok in results:
        if not ok:
            print(f"    - {label}")
    sys.exit(1)
else:
    print()
    sys.exit(0)
