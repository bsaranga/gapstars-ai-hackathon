from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .config import load_all
from .pipeline_events import triage_events

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
async def triage_endpoint(req: TriageRequest) -> StreamingResponse:
    """Stream NDJSON pipeline events for a bug markdown input."""
    deps = load_all()

    async def gen():
        async for event in triage_events(req.bug_markdown, deps=deps):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")
