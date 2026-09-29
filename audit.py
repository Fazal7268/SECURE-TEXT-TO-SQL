import sqlite3
import os
from datetime import datetime

AUDIT_DB = os.getenv("AUDIT_DB_PATH", "data/audit.db")


def init_db():
    os.makedirs(os.path.dirname(AUDIT_DB), exist_ok=True)
    con = sqlite3.connect(AUDIT_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            question    TEXT NOT NULL,
            sql_generated TEXT,
            confidence  TEXT,
            judge_score INTEGER,
            row_count   INTEGER,
            blocked     INTEGER DEFAULT 0,
            blocked_reason TEXT
        )
    """)
    con.commit()
    con.close()


def log_query(question: str, sql: str = None, confidence: str = None,
              judge_score: int = None, row_count: int = None,
              blocked: bool = False, blocked_reason: str = None):
    con = sqlite3.connect(AUDIT_DB)
    con.execute(
        """INSERT INTO query_log
           (timestamp, question, sql_generated, confidence, judge_score, row_count, blocked, blocked_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.utcnow().isoformat(),
            question,
            sql,
            confidence,
            judge_score,
            row_count,
            int(blocked),
            blocked_reason,
        ),
    )
    con.commit()
    con.close()


def get_history(limit: int = 50, blocked_only: bool = False) -> list[dict]:
    con = sqlite3.connect(AUDIT_DB)
    con.row_factory = sqlite3.Row

    if blocked_only:
        rows = con.execute(
            "SELECT * FROM query_log WHERE blocked = 1 ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM query_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    con.close()
    return [dict(r) for r in rows]
