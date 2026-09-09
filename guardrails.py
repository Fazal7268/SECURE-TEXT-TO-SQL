import re
import sqlparse

BLOCKED_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "ATTACH", "COPY",
}

class GuardrailViolation(Exception):
    pass

def check_sql_is_safe(sql: str) -> None:
    """Blocks any statement that modifies the database or runs admin commands."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        raise GuardrailViolation("Could not parse generated SQL statement.")

    for statement in parsed:
        stmt_type = statement.get_type()
        if stmt_type and stmt_type.upper() in BLOCKED_KEYWORDS:
            raise GuardrailViolation(
                f"Blocked operation: '{stmt_type}' statements are not permitted. Read-only queries only."
            )

    # Secondary check against keyword list in case sqlparse misses an inline keyword
    upper_sql = sql.upper()
    for kw in BLOCKED_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper_sql):
            raise GuardrailViolation(f"Blocked: query contains forbidden keyword '{kw}'.")

    if not upper_sql.strip().startswith("SELECT") and not upper_sql.strip().startswith("WITH"):
        raise GuardrailViolation("Only SELECT (or WITH ... SELECT) statements are allowed.")

def enforce_row_limit(sql: str, max_rows: int) -> str:
    """Appends LIMIT clause if one is not already present."""
    if re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return sql.rstrip().rstrip(";") + f" LIMIT {max_rows};"
