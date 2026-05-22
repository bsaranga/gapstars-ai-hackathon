from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import db
from .config import load_all
from .jobs import SENTINEL, store

db.init()

_STATIC_DIR = Path(__file__).parent / "static"
_UI_STATIC_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"

app = FastAPI(title="Bug Triage Dashboard")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(_UI_STATIC_DIR / "index.html")


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


class TriageRequest(BaseModel):
    bug_markdown: str


@app.post("/triage")
async def triage_start(req: TriageRequest) -> dict:
    """Start a triage job in the background and return its id.

    Both UI views subscribe to the same job via `/triage/{job_id}/stream`,
    so switching between `/` and `/dashboard` mid-run shows the same state.
    """
    deps = load_all()
    job = store.start(req.bug_markdown, deps)
    return {"job_id": job.id}


@app.get("/triage/current")
def triage_current() -> dict:
    """The currently *running* job id (or null). Finished runs are not
    auto-resumed — the user should opt into replaying them by clicking
    a row in the dashboard.
    """
    job = store.current()
    if job is None or job.finished:
        return {"job_id": None}
    return {"job_id": job.id, "finished": False, "event_count": len(job.events)}


@app.get("/triage/{job_id}/stream")
async def triage_stream(job_id: str) -> StreamingResponse:
    """NDJSON event stream for a job. If the job is still in memory we
    replay buffered events and tail live ones; if it has been evicted
    (e.g. after a server restart) we fall back to replaying the events
    persisted in the runs DB.
    """
    job = store.get(job_id)
    if job is not None:
        queue = await job.subscribe()

        async def gen_live():
            try:
                while True:
                    ev = await queue.get()
                    if ev is SENTINEL:
                        break
                    yield json.dumps(ev, default=str) + "\n"
            finally:
                job.unsubscribe(queue)

        return StreamingResponse(gen_live(), media_type="application/x-ndjson")

    row = db.get_run(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown job_id")

    async def gen_replay():
        for ev in row.get("events", []):
            yield json.dumps(ev, default=str) + "\n"

    return StreamingResponse(gen_replay(), media_type="application/x-ndjson")


@app.get("/runs")
def runs_list() -> dict:
    """Persisted run history, newest first. The currently-running job
    (if any) is flagged so the dashboard can stream it live instead of
    replaying from disk.
    """
    return {"runs": db.list_runs(), "current_job_id": store.current_id}


@app.get("/runs/{job_id}")
def run_detail(job_id: str) -> dict:
    row = db.get_run(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return row
