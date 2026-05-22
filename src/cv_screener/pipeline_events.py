from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from .agents import (
    aggregator_agent,
    communication_agent,
    cv_parser_agent,
    education_agent,
    experience_agent,
    jd_parser_agent,
    red_flags_agent,
    skills_agent,
)


def _dump(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump()
    return o


def _usage_tokens(result) -> dict:
    try:
        u = result.usage()
    except Exception:
        return {"input": 0, "output": 0, "total": 0}
    input_tok = (
        getattr(u, "input_tokens", None)
        or getattr(u, "request_tokens", None)
        or 0
    )
    output_tok = (
        getattr(u, "output_tokens", None)
        or getattr(u, "response_tokens", None)
        or 0
    )
    total = getattr(u, "total_tokens", None) or (input_tok + output_tok)
    return {"input": input_tok, "output": output_tok, "total": total}


async def _run_one(
    queue: asyncio.Queue,
    agent: Agent,
    name: str,
    prompt: str | dict,
):
    prompt_str = prompt if isinstance(prompt, str) else json.dumps(prompt)
    started = time.perf_counter()
    await queue.put({"type": "start", "agent": name, "input": prompt})
    try:
        result = await agent.run(prompt_str)
        output = _dump(result.output)
        tokens = _usage_tokens(result)
        await queue.put(
            {
                "type": "done",
                "agent": name,
                "output": output,
                "tokens": tokens,
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


async def screen_events(raw_cv: str, raw_jd: str) -> AsyncIterator[dict]:
    """Run the full screening pipeline, yielding events for each agent.

    Event shapes:
      {type: 'start',  agent, input}
      {type: 'done',   agent, output, tokens: {input, output, total}, elapsed_ms}
      {type: 'failed', agent, error, elapsed_ms}
      {type: 'pipeline_done',   recommendation}
      {type: 'pipeline_failed', error}
    """
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL: Any = object()

    async def run_pipeline() -> None:
        try:
            parsed_cv, jd = await asyncio.gather(
                _run_one(queue, cv_parser_agent, "parser_cv", raw_cv),
                _run_one(queue, jd_parser_agent, "parser_jd", raw_jd),
            )

            pair = {"cv": parsed_cv.model_dump(), "jd": jd.model_dump()}
            cv_only = {"cv": parsed_cv.model_dump()}
            comm = {"raw_cv": raw_cv, "summary": parsed_cv.summary}

            skills, experience, education, red_flags, communication = await asyncio.gather(
                _run_one(queue, skills_agent, "skills", pair),
                _run_one(queue, experience_agent, "experience", pair),
                _run_one(queue, education_agent, "education", pair),
                _run_one(queue, red_flags_agent, "red_flags", cv_only),
                _run_one(queue, communication_agent, "communication", comm),
            )

            agg_input = {
                "jd": jd.model_dump(),
                "skills": skills.model_dump(),
                "experience": experience.model_dump(),
                "education": education.model_dump(),
                "red_flags": red_flags.model_dump(),
                "communication": communication.model_dump(),
            }
            recommendation = await _run_one(
                queue, aggregator_agent, "aggregator", agg_input
            )
            await queue.put(
                {"type": "pipeline_done", "recommendation": recommendation.model_dump()}
            )
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
