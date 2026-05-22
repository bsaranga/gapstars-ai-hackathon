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
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              key TEXT NOT NULL,
              name TEXT NOT NULL UNIQUE,
              description TEXT,
              created_at REAL NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS issues (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id INTEGER NOT NULL,
              job_id TEXT,
              bug_id TEXT,
              title TEXT NOT NULL,
              severity TEXT,
              priority TEXT,
              status TEXT NOT NULL DEFAULT 'Open',
              assignee TEXT,
              team TEXT,
              jira_ticket TEXT,
              final_json TEXT,
              created_at REAL NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id)
            )
            """
        )
        # Add project_id to runs if missing (idempotent migration).
        cols = [r[1] for r in c.execute("PRAGMA table_info(runs)").fetchall()]
        if "project_id" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN project_id INTEGER")


def insert_run(job_id: str, bug_markdown: str, project_id: int | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO runs(job_id, started_at, bug_markdown, project_id) "
            "VALUES(?, ?, ?, ?)",
            (job_id, time.time(), bug_markdown, project_id),
        )


# ---------- projects ----------


def _derive_key(name: str) -> str:
    words = [w for w in name.upper().split() if w]
    if not words:
        return "XX"
    if len(words) == 1:
        return words[0][:2]
    return "".join(w[0] for w in words[:3])


def list_projects() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, key, name, description, created_at "
            "FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def create_project(
    name: str, key: str | None = None, description: str | None = None
) -> int:
    name = name.strip()
    key = (key or _derive_key(name)).strip().upper()[:4] or "XX"
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO projects(name, key, description, created_at) "
            "VALUES(?, ?, ?, ?)",
            (name, key, description, time.time()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_project(project_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, key, name, description, created_at "
            "FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------- issues ----------


def create_issue(project_id: int, job_id: str | None, final: dict) -> int:
    artifacts = (final or {}).get("artifacts") or {}
    assignee = (final or {}).get("suggested_assignee") or {}
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO issues(
                 project_id, job_id, bug_id, title, severity, priority,
                 status, assignee, team, jira_ticket, final_json, created_at
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                job_id,
                final.get("bug_id"),
                final.get("summary") or "(no title)",
                final.get("severity"),
                final.get("priority"),
                "Open",
                assignee.get("name"),
                final.get("suggested_owner_team"),
                artifacts.get("jira_ticket"),
                json.dumps(final, default=str),
                time.time(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_issue(issue_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    raw = d.pop("final_json", None)
    d["final"] = json.loads(raw) if raw else None
    return d


def list_issues(project_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT id, project_id, job_id, bug_id, title, severity, priority,
                      status, assignee, team, jira_ticket, created_at
                 FROM issues
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


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
