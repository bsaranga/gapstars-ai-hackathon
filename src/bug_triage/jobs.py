"""Shared job store for the triage pipeline.

A single triage run is a `Job`: it buffers every event it sees so that
clients which connect *late* (or switch between the `/` and `/dashboard`
views mid-run) can replay the full history and then continue tailing
live events. There is no UI for parallel jobs, but the store is keyed
by id so it would not break if we added one.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from . import db
from .config import TriageDeps
from .pipeline_events import triage_events

_SENTINEL: Any = object()


class Job:
    def __init__(self, job_id: str, bug_markdown: str) -> None:
        self.id = job_id
        self.bug_markdown = bug_markdown
        self.events: list[dict] = []
        self.finished: bool = False
        self.subscribers: list[asyncio.Queue] = []
        self.task: asyncio.Task | None = None

    async def _broadcast(self, ev: dict | object) -> None:
        for q in list(self.subscribers):
            await q.put(ev)

    async def run(self, deps: TriageDeps) -> None:
        try:
            async for ev in triage_events(self.bug_markdown, deps=deps):
                self.events.append(ev)
                await self._broadcast(ev)
        finally:
            self.finished = True
            try:
                db.finalize_run(self.id, self.events)
            except Exception:  # noqa: BLE001
                pass
            await self._broadcast(_SENTINEL)

    async def subscribe(self) -> asyncio.Queue:
        """Returns a queue pre-populated with buffered events.

        If the job is already finished, the queue ends with the sentinel
        so the caller drains the replay and exits cleanly.
        """
        q: asyncio.Queue = asyncio.Queue()
        for ev in self.events:
            await q.put(ev)
        if self.finished:
            await q.put(_SENTINEL)
        else:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self.current_id: str | None = None

    def start(
        self,
        bug_markdown: str,
        deps: TriageDeps,
        project_id: int | None = None,
    ) -> Job:
        job = Job(uuid.uuid4().hex, bug_markdown)
        self._jobs[job.id] = job
        self.current_id = job.id
        db.insert_run(job.id, bug_markdown, project_id=project_id)
        job.task = asyncio.create_task(job.run(deps))
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def current(self) -> Job | None:
        if self.current_id is None:
            return None
        return self._jobs.get(self.current_id)


SENTINEL = _SENTINEL
store = JobStore()
