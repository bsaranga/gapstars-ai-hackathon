"""SQLite store for triage runs.

Each run is one row keyed by `job_id` (matches `jobs.Job.id`). We persist
the raw bug markdown, the full event stream, and a few denormalised
summary fields pulled from the final report so the run list can render
without parsing every event blob.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "runs.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL UNIQUE,
              started_at REAL NOT NULL,
              finished_at REAL,
              bug_markdown TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'running',
              bug_id TEXT,
              summary TEXT,
              severity TEXT,
              priority TEXT,
              events_json TEXT
            )
            """
        )


def insert_run(job_id: str, bug_markdown: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO runs(job_id, started_at, bug_markdown) VALUES(?, ?, ?)",
            (job_id, time.time(), bug_markdown),
        )


def finalize_run(job_id: str, events: list[dict]) -> None:
    final = next(
        (e.get("final") for e in events if e.get("type") == "pipeline_done"), None
    )
    failed_ev = next((e for e in events if e.get("type") == "pipeline_failed"), None)

    if final:
        status_raw = final.get("status") or ""
        if status_raw == "Triaged":
            status = "triaged"
        elif status_raw == "Needs More Information":
            status = "needs_info"
        else:
            status = "done"
        bug_id = final.get("bug_id")
        summary = final.get("summary")
        severity = final.get("severity")
        priority = final.get("priority")
    elif failed_ev:
        status = "failed"
        bug_id = None
        summary = failed_ev.get("error")
        severity = None
        priority = None
    else:
        status = "failed"
        bug_id = None
        summary = "pipeline ended without final event"
        severity = None
        priority = None

    with _conn() as c:
        c.execute(
            """UPDATE runs
                 SET finished_at=?, status=?, bug_id=?, summary=?,
                     severity=?, priority=?, events_json=?
               WHERE job_id=?""",
            (
                time.time(),
                status,
                bug_id,
                summary,
                severity,
                priority,
                json.dumps(events, default=str),
                job_id,
            ),
        )


def list_runs(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT job_id, started_at, finished_at, status,
                      bug_id, summary, severity, priority
                 FROM runs
                ORDER BY started_at DESC
                LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM runs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["events"] = json.loads(d.pop("events_json") or "[]")
    return d
