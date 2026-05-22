from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "runs.db"
_DB_PATH = Path(os.getenv("CV_SCREENER_DB", str(_DEFAULT_PATH)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                cv_text TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                candidate_name TEXT,
                jd_title TEXT,
                recommendation TEXT NOT NULL,
                score INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                agents_json TEXT NOT NULL,
                recommendation_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_run    ON chat_messages(run_id, id);
            """
        )


def save_run(
    *,
    cv_text: str,
    jd_text: str,
    agents: dict[str, dict[str, Any]],
    recommendation: dict[str, Any],
) -> int:
    parser_cv_out = agents.get("parser_cv", {}).get("output") or {}
    parser_jd_out = agents.get("parser_jd", {}).get("output") or {}
    candidate_name = parser_cv_out.get("full_name")
    jd_title = parser_jd_out.get("title")
    total_tokens = sum(
        (a.get("tokens") or {}).get("total", 0) for a in agents.values()
    )
    elapsed_ms = max(
        (a.get("elapsed_ms", 0) for a in agents.values()), default=0
    )  # wall-clock isn't sum because of parallelism — use max as a rough proxy

    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO runs
              (created_at, cv_text, jd_text, candidate_name, jd_title,
               recommendation, score, total_tokens, elapsed_ms,
               agents_json, recommendation_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _now(),
                cv_text,
                jd_text,
                candidate_name,
                jd_title,
                recommendation["recommendation"],
                recommendation["overall_score"],
                total_tokens,
                elapsed_ms,
                json.dumps(agents),
                json.dumps(recommendation),
            ),
        )
        return int(cur.lastrowid)


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, created_at, candidate_name, jd_title,
                   recommendation, score, total_tokens
            FROM runs ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        chat = c.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "cv_text": row["cv_text"],
            "jd_text": row["jd_text"],
            "candidate_name": row["candidate_name"],
            "jd_title": row["jd_title"],
            "recommendation": json.loads(row["recommendation_json"]),
            "agents": json.loads(row["agents_json"]),
            "score": row["score"],
            "total_tokens": row["total_tokens"],
            "elapsed_ms": row["elapsed_ms"],
            "chat": [dict(m) for m in chat],
        }


def get_chat_messages(run_id: int) -> list[dict[str, str]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM chat_messages WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_chat_message(run_id: int, role: str, content: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO chat_messages (run_id, role, content, created_at) VALUES (?,?,?,?)",
            (run_id, role, content, _now()),
        )


def delete_run(run_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM runs WHERE id = ?", (run_id,))
