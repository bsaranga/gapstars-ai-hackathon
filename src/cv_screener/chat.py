from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("TOGETHER_API_KEY")
        if not api_key:
            raise RuntimeError("TOGETHER_API_KEY is not set.")
        _client = AsyncOpenAI(
            base_url="https://api.together.xyz/v1", api_key=api_key
        )
    return _client


_SYSTEM_TMPL = """You help a hiring team understand, verify, and probe an
automated CV screening result. Answer **only** from the data shown below; if
something is not covered, say so explicitly rather than guessing. Be concise.

When the user asks "why" questions, point at the specific specialist output
(skills / experience / education / red_flags / communication) that drove the
answer. When they ask "what would change the verdict", reason about which
scores would need to move and by how much.

=== JOB DESCRIPTION (raw) ===
{jd_raw}

=== PARSED JOB DESCRIPTION ===
{jd_parsed}

=== CANDIDATE CV (raw) ===
{cv_raw}

=== PARSED CV ===
{cv_parsed}

=== SPECIALIST EVALUATIONS ===

Skills:
{skills}

Experience:
{experience}

Education:
{education}

Red flags:
{red_flags}

Communication:
{communication}

=== FINAL RECOMMENDATION ===
{recommendation}
"""


def _agent_output(agents: dict[str, Any], name: str) -> str:
    out = (agents.get(name) or {}).get("output") or {}
    return json.dumps(out, indent=2)


def build_system_prompt(run: dict[str, Any]) -> str:
    agents = run["agents"]
    return _SYSTEM_TMPL.format(
        jd_raw=run["jd_text"],
        jd_parsed=_agent_output(agents, "parser_jd"),
        cv_raw=run["cv_text"],
        cv_parsed=_agent_output(agents, "parser_cv"),
        skills=_agent_output(agents, "skills"),
        experience=_agent_output(agents, "experience"),
        education=_agent_output(agents, "education"),
        red_flags=_agent_output(agents, "red_flags"),
        communication=_agent_output(agents, "communication"),
        recommendation=json.dumps(run["recommendation"], indent=2),
    )


def _model() -> str:
    return (
        os.getenv("CV_SCREENER_MODEL_CHAT")
        or os.getenv("CV_SCREENER_MODEL_AGGREGATOR")
        or "openai/gpt-oss-20b"
    )


async def chat_stream(
    run: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
) -> AsyncIterator[str]:
    """Yield content chunks for the assistant's reply."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": build_system_prompt(run)}
    ]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": user_message})

    client = _get_client()
    stream = await client.chat.completions.create(
        model=_model(),
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
