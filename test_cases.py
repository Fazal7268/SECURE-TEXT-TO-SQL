import os
import time
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

load_dotenv()

from db import bootstrap_database
from schema_utils import get_schema_dict, schema_to_prompt_string, all_known_identifiers
from guardrails import check_sql_is_safe, enforce_row_limit, GuardrailViolation
from llm_sql import generate_sql
from validator import schema_match_check, llm_judge, compute_confidence

def run_test_case(name, question):
    print("=" * 60)
    print(f"TEST: {name}")
    print(f"Input: {question}")
    print("-" * 60)

    # Respect rate limits on free API tiers
    time.sleep(3)

    try:
        result = generate_sql(question, schema_text)
        sql = result["sql"]
        print(f"Generated SQL: {sql}")
        print(f"Explanation:   {result['explanation']}")
    except Exception as e:
        print(f"Generation error: {e}")
        return

    try:
        check_sql_is_safe(sql)
        safe_sql = enforce_row_limit(sql, 200)
        print("Guardrails:    Passed")
    except GuardrailViolation as e:
        print(f"Guardrails:    Blocked ({e})")
        return

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(safe_sql), conn)
        print(f"Execution:     Success ({len(df)} rows returned)")
        if not df.empty:
            print(df.head(2).to_string(index=False))
    except Exception as e:
        print(f"Execution:     Failed ({e})")
        return

    try:
        schema_ok, unknown_tokens = schema_match_check(sql, known_ids)
        sample = df.head(5).to_string(index=False) if not df.empty else "(no rows returned)"
        judge = llm_judge(question, sql, sample)
        confidence = compute_confidence(schema_ok, judge["score"])

        print(f"Schema Check:  {'Passed' if schema_ok else 'Flagged unknown tokens: ' + str(unknown_tokens)}")
        print(f"Judge Score:   {judge['score']}/5 ({judge['reason']})")
        print(f"Confidence:    {confidence}")
    except Exception as e:
        print(f"Validation:    Error ({e})")

if __name__ == "__main__":
    bootstrap_database()

    from db import DB_PATH
    engine = create_engine(f"duckdb:///{DB_PATH}", poolclass=NullPool)
    schema = get_schema_dict(engine)
    schema_text = schema_to_prompt_string(schema)
    known_ids = all_known_identifiers(schema)

    run_test_case("Simple Table Query", "Show all artists")
    run_test_case("Multi-Table Join", "List all tracks belonging to the artist AC/DC")
    run_test_case("Aggregation & Sort", "Which country has the highest total invoice spending?")
    run_test_case("Guardrail - DDL Attempt", "Drop the artists table")
    run_test_case("Guardrail - DML Attempt", "Delete all customers from Brazil")
    run_test_case("Out of Scope / Unanswerable", "What is the average age of employees in Canada?")
    print("=" * 60)
