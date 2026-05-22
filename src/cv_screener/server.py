from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import auth, db
from .chat import chat_stream
from .pipeline_events import screen_events

app = FastAPI(title="CV Screener")
app.add_middleware(
    SessionMiddleware,
    secret_key=auth.session_secret(),
    same_site="lax",
    https_only=False,
)

_PKG_DIR = Path(__file__).parent
_STATIC = _PKG_DIR / "static"
_EXAMPLES = _PKG_DIR.parent.parent / "examples"


@app.on_event("startup")
async def _startup() -> None:
    db.init()


# ---------- auth ----------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(auth.render_login_html(error))


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not auth.is_configured():
        return HTMLResponse(
            auth.render_login_html(
                "Server not configured: set CV_SCREENER_PASSWORD in .env"
            ),
            status_code=500,
        )
    if not auth.credentials_valid(username, password):
        return HTMLResponse(
            auth.render_login_html("Invalid username or password."),
            status_code=401,
        )
    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------- pages ----------


@app.get("/")
async def index(request: Request):
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=303)
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


# ---------- protected API ----------


class ScreenRequest(BaseModel):
    cv: str
    jd: str


class ChatRequest(BaseModel):
    message: str


@app.get(
    "/example/cv",
    response_class=PlainTextResponse,
    dependencies=[Depends(auth.require_auth)],
)
async def example_cv() -> str:
    p = _EXAMPLES / "cv_example.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


@app.get(
    "/example/jd",
    response_class=PlainTextResponse,
    dependencies=[Depends(auth.require_auth)],
)
async def example_jd() -> str:
    p = _EXAMPLES / "jd_example.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


@app.post("/screen", dependencies=[Depends(auth.require_auth)])
async def screen_endpoint(req: ScreenRequest):
    async def gen():
        agents: dict[str, dict[str, Any]] = {}
        recommendation: dict[str, Any] | None = None

        async for event in screen_events(req.cv, req.jd):
            etype = event.get("type")
            if etype == "start":
                agents[event["agent"]] = {
                    "state": "running",
                    "input": event["input"],
                }
            elif etype == "done":
                agents.setdefault(event["agent"], {}).update(
                    {
                        "state": "done",
                        "output": event["output"],
                        "tokens": event["tokens"],
                        "elapsed_ms": event["elapsed_ms"],
                    }
                )
            elif etype == "failed":
                agents.setdefault(event["agent"], {}).update(
                    {
                        "state": "failed",
                        "error": event["error"],
                        "elapsed_ms": event["elapsed_ms"],
                    }
                )
            elif etype == "pipeline_done":
                recommendation = event["recommendation"]

            yield json.dumps(event) + "\n"

        if recommendation is not None:
            run_id = db.save_run(
                cv_text=req.cv,
                jd_text=req.jd,
                agents=agents,
                recommendation=recommendation,
            )
            yield json.dumps({"type": "run_saved", "run_id": run_id}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/runs", dependencies=[Depends(auth.require_auth)])
async def list_runs() -> list[dict[str, Any]]:
    return db.list_runs()


@app.get("/runs/{run_id}", dependencies=[Depends(auth.require_auth)])
async def get_run(run_id: int) -> dict[str, Any]:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.delete("/runs/{run_id}", dependencies=[Depends(auth.require_auth)])
async def delete_run(run_id: int) -> dict[str, str]:
    db.delete_run(run_id)
    return {"status": "deleted"}


@app.post("/runs/{run_id}/chat", dependencies=[Depends(auth.require_auth)])
async def chat_endpoint(run_id: int, req: ChatRequest):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    history = db.get_chat_messages(run_id)

    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(400, "message must not be empty")

    db.add_chat_message(run_id, "user", user_msg)

    async def gen():
        full = []
        try:
            async for chunk in chat_stream(run, history, user_msg):
                full.append(chunk)
                yield chunk
        finally:
            if full:
                db.add_chat_message(run_id, "assistant", "".join(full))

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
