from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import litellm

_DEFAULT_CHAT_MODEL = "together_ai/openai/gpt-oss-20b"


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
        or _DEFAULT_CHAT_MODEL
    )


async def chat_stream(
    run: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
) -> AsyncIterator[str]:
    """Yield content chunks for the assistant's reply.

    Routes through LiteLLM so the same code talks to Together / OpenAI /
    Anthropic / Gemini / Bedrock depending on the configured model prefix.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": build_system_prompt(run)}
    ]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    messages.append({"role": "user", "content": user_message})

    stream = await litellm.acompletion(
        model=_model(),
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        try:
            choices = chunk.choices
        except AttributeError:
            choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if delta is None and isinstance(choices[0], dict):
            delta = choices[0].get("delta")
        content = getattr(delta, "content", None) if delta is not None else None
        if content is None and isinstance(delta, dict):
            content = delta.get("content")
        if content:
            yield content
