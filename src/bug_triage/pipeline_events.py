from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from .agents import analyzer_agent, artifact_agent, bug_parser_agent, triage_agent
from .config import TriageDeps, load_all
from .models import AnalysisOutput, BugReport, FinalReport, NotifyContact
from .rules import build_notify_list, classify, select_team


def _dump(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump()
    return o


def _usage_tokens(result) -> dict:
    try:
        u = result.usage()
    except Exception:
        return {"input": 0, "output": 0, "total": 0}
    inp = getattr(u, "input_tokens", None) or getattr(u, "request_tokens", None) or 0
    out = getattr(u, "output_tokens", None) or getattr(u, "response_tokens", None) or 0
    total = getattr(u, "total_tokens", None) or (inp + out)
    return {"input": inp, "output": out, "total": total}


async def _run_one(
    queue: asyncio.Queue,
    agent: Agent,
    name: str,
    prompt: str | dict,
    deps: Any = None,
):
    prompt_str = prompt if isinstance(prompt, str) else json.dumps(prompt)
    started = time.perf_counter()
    await queue.put({"type": "start", "agent": name, "input": prompt})
    try:
        result = await (
            agent.run(prompt_str, deps=deps) if deps is not None else agent.run(prompt_str)
        )
        await queue.put(
            {
                "type": "done",
                "agent": name,
                "output": _dump(result.output),
                "tokens": _usage_tokens(result),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return result.output
    except Exception as exc:  # noqa: BLE001
        await queue.put(
            {
                "type": "failed",
                "agent": name,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        raise


async def triage_events(
    raw_markdown: str, deps: TriageDeps | None = None
) -> AsyncIterator[dict]:
    """Stream per-agent events from the bug-triage pipeline.

    Event shapes:
      {type: 'start',  agent, input}
      {type: 'done',   agent, output, tokens, elapsed_ms}
      {type: 'failed', agent, error, elapsed_ms}
      {type: 'gate',   verdict, blocking_fields}
      {type: 'rule',   severity, priority, rule_applied, team}
      {type: 'pipeline_done',   final}
      {type: 'pipeline_failed', error}
    """
    deps = deps or load_all()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL: Any = object()

    async def run_pipeline() -> None:
        try:
            bug: BugReport = await _run_one(queue, bug_parser_agent, "parser", raw_markdown)
            if not bug.bug_id:
                bug = bug.model_copy(
                    update={"bug_id": f"BUG-{uuid.uuid4().hex[:10].upper()}"}
                )

            analysis: AnalysisOutput = await _run_one(
                queue, analyzer_agent, "analyzer", bug.model_dump()
            )

            await queue.put(
                {
                    "type": "gate",
                    "verdict": analysis.completeness.verdict,
                    "blocking_fields": analysis.completeness.blocking_fields,
                }
            )

            if analysis.completeness.verdict == "needs_more_info":
                final = FinalReport(
                    bug_id=bug.bug_id or "",
                    summary=analysis.summary,
                    status="Needs More Information",
                    missing_information=analysis.missing_information,
                    blocking_fields=analysis.completeness.blocking_fields,
                    suggested_repro_steps=analysis.inferred_repro_steps,
                    rationale=analysis.completeness.rationale,
                )
                await queue.put({"type": "pipeline_done", "final": final.model_dump()})
                return

            verdict = classify(bug, analysis, deps.rules)
            team = select_team(analysis, deps.teams)
            await queue.put(
                {
                    "type": "rule",
                    "severity": verdict.severity,
                    "priority": verdict.priority,
                    "rule_id": verdict.rule_id,
                    "rule_applied": verdict.rule_applied,
                    "team": team.name,
                }
            )

            decision = await _run_one(
                queue,
                triage_agent,
                "triage",
                {
                    "analysis": analysis.model_dump(),
                    "severity": verdict.severity,
                    "priority": verdict.priority,
                    "team_id": team.id,
                },
                deps=deps,
            )

            notify = [NotifyContact(**n) for n in build_notify_list(team, verdict.priority)]

            artifacts = await _run_one(
                queue,
                artifact_agent,
                "artifact",
                {
                    "bug": bug.model_dump(),
                    "analysis": analysis.model_dump(),
                    "severity": verdict.severity,
                    "priority": verdict.priority,
                    "rule_id": verdict.rule_id,
                    "team_name": team.name,
                    "jira_project": team.jira_project,
                    "slack_channel": team.slack_channel,
                    "assignee": decision.suggested_assignee.model_dump(
                        include={"id", "name"}
                    ),
                    "notify": [n.model_dump() for n in notify],
                },
                deps=deps,
            )

            final = FinalReport(
                bug_id=bug.bug_id or "",
                summary=analysis.summary,
                status="Triaged",
                severity=verdict.severity,
                priority=verdict.priority,
                missing_information=analysis.missing_information,
                suggested_repro_steps=analysis.inferred_repro_steps
                or bug.steps_to_reproduce,
                suggested_owner_team=team.name,
                suggested_assignee=decision.suggested_assignee,
                notify=notify,
                triage_recommendation=decision.triage_recommendation,
                rule_applied=(
                    f"{verdict.rule_id}: {verdict.rule_applied} → "
                    f"{verdict.severity} / {verdict.priority}"
                ),
                artifacts=artifacts,
            )
            await queue.put({"type": "pipeline_done", "final": final.model_dump()})
        except Exception as exc:  # noqa: BLE001
            await queue.put(
                {"type": "pipeline_failed", "error": f"{type(exc).__name__}: {exc}"}
            )
        finally:
            await queue.put(SENTINEL)

    task = asyncio.create_task(run_pipeline())
    try:
        while True:
            ev = await queue.get()
            if ev is SENTINEL:
                break
            yield ev
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
