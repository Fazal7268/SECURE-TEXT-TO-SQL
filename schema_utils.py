"""
schema_utils.py
Extracts database schema into a compact JSON-serializable structure.
Injected into the LLM prompt on every request instead of raw table contents.
"""

from sqlalchemy import inspect, text


def _get_duckdb_schema(engine) -> dict:
    """Extract schema directly using DuckDB's information_schema to avoid
    SQLAlchemy pg_catalog reflection issues across different environments."""
    schema = {}
    with engine.connect() as conn:
        cols = conn.execute(text("""
            SELECT table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'main'
            ORDER BY table_name, ordinal_position
        """)).fetchall()

        for tbl, c_name, c_type in cols:
            if tbl not in schema:
                schema[tbl] = {"columns": [], "foreign_keys": []}
            schema[tbl]["columns"].append({"name": c_name, "type": str(c_type)})

        try:
            fks = conn.execute(text("""
                SELECT table_name, constraint_column_names, 
                       referenced_table, referenced_column_names
                FROM duckdb_constraints()
                WHERE constraint_type = 'FOREIGN KEY'
            """)).fetchall()
            for tbl, c_cols, ref_tbl, ref_cols in fks:
                if tbl in schema:
                    col_list = list(c_cols) if c_cols else []
                    ref_list = list(ref_cols) if ref_cols else []
                    schema[tbl]["foreign_keys"].append({
                        "column": col_list,
                        "references": f"{ref_tbl}({ref_list})",
                    })
        except Exception:
            pass
    return schema


def get_schema_dict(engine) -> dict:
    """Return {table_name: {columns: [...], foreign_keys: [...]}}"""
    # DuckDB has known pg_catalog reflection issues with newer SQLAlchemy versions
    if getattr(engine.dialect, "name", "") == "duckdb":
        try:
            return _get_duckdb_schema(engine)
        except Exception:
            pass

    inspector = inspect(engine)
    schema = {}

    for table_name in inspector.get_table_names():
        try:
            columns = inspector.get_columns(table_name)
        except Exception:
            columns = []
        try:
            fks = inspector.get_foreign_keys(table_name)
        except Exception:
            fks = []

        schema[table_name] = {
            "columns": [
                {"name": c["name"], "type": str(c["type"])} for c in columns
            ],
            "foreign_keys": [
                {
                    "column": fk.get("constrained_columns", []),
                    "references": f'{fk.get("referred_table", "")}({fk.get("referred_columns", [])})',
                }
                for fk in fks
            ],
        }
    return schema


def schema_to_prompt_string(schema: dict) -> str:
    """Render the schema dict as a compact text block for the LLM prompt."""
    lines = []
    for table, meta in schema.items():
        cols = ", ".join(f'{c["name"]} ({c["type"]})' for c in meta["columns"])
        lines.append(f"TABLE {table}: {cols}")
        for fk in meta["foreign_keys"]:
            lines.append(f"  FK: {fk['column']} -> {fk['references']}")
    return "\n".join(lines)


def all_known_identifiers(schema: dict) -> set:
    """Flat set of every valid table.column and bare column name, used by
    the hallucination validator to check the LLM didn't invent a field."""
    ids = set()
    for table, meta in schema.items():
        ids.add(table.lower())
        for c in meta["columns"]:
            ids.add(c["name"].lower())
            ids.add(f'{table}.{c["name"]}'.lower())
    return ids
