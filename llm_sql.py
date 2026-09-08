import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
client = genai.Client()

class GenerateSql(BaseModel):
    sql: str
    explanation: str

SYSTEM_PROMPT = """You are a SQL generator. Translate the user's natural language question into a single read-only SQL SELECT statement for the given schema.

Rules:
- Generate SELECT statements only. Never generate DDL or DML (DROP, DELETE, UPDATE, INSERT, ALTER).
- Reference only existing tables and columns from the provided schema.
- If the schema cannot fully answer the question, return the best read-only query possible and note the limitation in the explanation.
- Always use explicit JOINs with ON clauses.

Schema:
{schema}
"""

def generate_sql(question: str, schema_text: str) -> dict:
    """Sends the question + schema to Gemini and returns structured SQL output."""
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(schema=schema_text),
            response_mime_type="application/json",
            response_schema=GenerateSql,
        ),
    )

    try:
        data = json.loads(response.text)
        return {
            "sql": data["sql"].strip(),
            "explanation": data["explanation"].strip(),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as err:
        raise RuntimeError(f"Could not parse model response: {response.text}") from err
