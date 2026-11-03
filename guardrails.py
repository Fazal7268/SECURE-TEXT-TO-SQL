import re
import sqlparse

BLOCKED_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "ATTACH", "DETACH", "COPY",
    "INSTALL", "LOAD", "PRAGMA", "EXPORT", "IMPORT",
    "READ_CSV", "READ_PARQUET", "READ_JSON", "READ_BLOB", "READ_TEXT",
    "WRITE_CSV", "WRITE_PARQUET", "EXEC", "EXECUTE",
}

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above)\s+instructions?",
    r"you\s+are\s+now",
    r"system\s+prompt",
    r"bypass\s+guardrails?",
    r"developer\s+mode",
    r"jailbreak",
    r"disregard\s+all",
]


class GuardrailViolation(Exception):
    pass


def sanitize_user_input(question: str, max_chars: int = 300) -> str:
    """Validates and sanitizes raw user question before it reaches the LLM."""
    clean = question.strip()
    if not clean:
        raise GuardrailViolation("Question cannot be empty.")

    if len(clean) > max_chars:
        raise GuardrailViolation(
            f"Question exceeds maximum length of {max_chars} characters (received {len(clean)})."
        )

    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE):
            raise GuardrailViolation("Input contains a blocked adversarial prompt pattern.")

    return clean


def check_sql_is_safe(sql: str) -> None:
    """Blocks any statement that modifies the database, reads external files,
    or attempts multi-statement execution."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        raise GuardrailViolation("Could not parse generated SQL statement.")

    # Prevent SQL injection via stacked/multi-statements
    if len(parsed) > 1:
        raise GuardrailViolation("Multiple statements in a single query are not permitted.")

    statement = parsed[0]
    stmt_type = statement.get_type()
    if stmt_type and stmt_type.upper() in BLOCKED_KEYWORDS:
        raise GuardrailViolation(
            f"Blocked operation: '{stmt_type}' statements are not permitted. Read-only queries only."
        )

    # Secondary check against keyword list in case sqlparse misses an inline keyword/function
    upper_sql = sql.upper()
    for kw in BLOCKED_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper_sql):
            raise GuardrailViolation(f"Blocked: query contains forbidden keyword or function '{kw}'.")

    if not upper_sql.strip().startswith("SELECT") and not upper_sql.strip().startswith("WITH"):
        raise GuardrailViolation("Only SELECT (or WITH ... SELECT) statements are allowed.")


def enforce_row_limit(sql: str, max_rows: int) -> str:
    """Appends LIMIT clause if one is not already present."""
    if re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return sql.rstrip().rstrip(";") + f" LIMIT {max_rows};"
