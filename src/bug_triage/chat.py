"""Chat-completion helper for the triage results chat widget.

Uses the raw `openai.AsyncOpenAI` client against Together AI's OpenAI-
compatible endpoint, because Pydantic-AI's typed-output guarantee adds
no value for free-form chat. The system prompt is rebuilt from the run
on every turn (the run is immutable once finished), so we don't have
to round-trip a tool-call context.
"""

from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

_KEEP_EVENT_KEYS = {
    "type",
    "agent",
    "rule_id",
    "verdict",
    "severity",
    "priority",
    "team",
    "blocking_fields",
}
_INTERESTING_EVENT_TYPES = {"done", "rule", "gate", "pipeline_failed"}


def _client() -> AsyncOpenAI:
    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise RuntimeError("TOGETHER_API_KEY is not set.")
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.together.xyz/v1",
    )


def _model() -> str:
    return os.getenv(
        "BUG_TRIAGE_MODEL_CHAT",
        os.getenv("BUG_TRIAGE_MODEL_ARTIFACT", "openai/gpt-oss-120b"),
    )


def build_system_prompt(run: dict) -> str:
    bug_markdown = run.get("bug_markdown") or ""
    events = run.get("events") or []
    final = next(
        (e.get("final") for e in events if e.get("type") == "pipeline_done"),
        None,
    )
    summary_events = [
        {k: v for k, v in e.items() if k in _KEEP_EVENT_KEYS}
        for e in events
        if e.get("type") in _INTERESTING_EVENT_TYPES
    ]
    final_blob = json.dumps(final, indent=2, default=str) if final else "(no final report)"
    events_blob = json.dumps(summary_events, indent=2, default=str)
    return (
        "You are a helpful assistant answering questions about ONE specific bug "
        "triage run. Stay grounded in the artefacts below — do not invent "
        "fields that aren't present. Be concise; quote exact values from the "
        "final report when relevant.\n\n"
        "## Original bug report (markdown)\n"
        f"---\n{bug_markdown}\n---\n\n"
        "## Final report (structured)\n"
        f"```json\n{final_blob}\n```\n\n"
        "## Pipeline events (summary)\n"
        f"```json\n{events_blob}\n```\n"
    )


async def reply(run: dict, history: list[dict], user_content: str) -> str:
    """Build the message list and return the assistant's reply text."""
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(run)}
    ]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_content})
    client = _client()
    resp = await client.chat.completions.create(
        model=_model(),
        messages=messages,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""
