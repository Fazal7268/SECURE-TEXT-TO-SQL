"""
schema_utils.py
Uses SQLAlchemy's inspection API to extract the database schema into a
compact JSON-serializable structure. This is what gets injected into the
LLM prompt on every request instead of raw table contents.
"""

from sqlalchemy import inspect


def get_schema_dict(engine) -> dict:
    """Return {table_name: {columns: [...], foreign_keys: [...]}}"""
    inspector = inspect(engine)
    schema = {}

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        fks = inspector.get_foreign_keys(table_name)

        schema[table_name] = {
            "columns": [
                {"name": c["name"], "type": str(c["type"])} for c in columns
            ],
            "foreign_keys": [
                {
                    "column": fk["constrained_columns"],
                    "references": f'{fk["referred_table"]}({fk["referred_columns"]})',
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
