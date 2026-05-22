from __future__ import annotations

import json
import os
from typing import Literal

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

Role = Literal["parser", "analyzer", "triage", "artifact"]

_DEFAULT_MODEL = "openai/gpt-oss-120b"
_ENV_BY_ROLE: dict[Role, str] = {
    "parser": "BUG_TRIAGE_MODEL_PARSER",
    "analyzer": "BUG_TRIAGE_MODEL_ANALYZER",
    "triage": "BUG_TRIAGE_MODEL_TRIAGE",
    "artifact": "BUG_TRIAGE_MODEL_ARTIFACT",
}


class _TogetherCompatTransport(httpx.AsyncHTTPTransport):
    """Rewrites outgoing /chat/completions bodies for Together AI quirks.

    Together's API rejects assistant messages with ``content: null`` (it
    returns a generic "Input validation error" 400). OpenAI spec allows
    null content when the assistant message only contains ``tool_calls``,
    and Pydantic-AI emits it that way during multi-turn tool calls. We
    rewrite ``null`` → ``""`` on assistant messages so the tool-call loop
    can complete.
    """

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") and request.content:
            try:
                body = json.loads(request.content)
                changed = False
                for m in body.get("messages", []):
                    if m.get("role") == "assistant" and m.get("content") is None:
                        m["content"] = ""
                        changed = True
                if changed:
                    new_content = json.dumps(body).encode()
                    new_headers = dict(request.headers)
                    new_headers["content-length"] = str(len(new_content))
                    request = httpx.Request(
                        method=request.method,
                        url=request.url,
                        headers=new_headers,
                        content=new_content,
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        return await super().handle_async_request(request)


def _together_model(role: Role) -> OpenAIChatModel:
    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TOGETHER_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    model_name = os.getenv(_ENV_BY_ROLE[role], _DEFAULT_MODEL)
    http_client = httpx.AsyncClient(transport=_TogetherCompatTransport())
    provider = OpenAIProvider(
        base_url="https://api.together.xyz/v1",
        api_key=api_key,
        http_client=http_client,
    )
    return OpenAIChatModel(model_name, provider=provider)


def make_agent(
    role: Role,
    *,
    output_type,
    system_prompt: str,
    deps_type: type | None = None,
) -> Agent:
    """Construct a Pydantic-AI Agent for a given role."""
    kwargs: dict = {
        "model": _together_model(role),
        "output_type": output_type,
        "system_prompt": system_prompt,
        "retries": 2,
    }
    if deps_type is not None:
        kwargs["deps_type"] = deps_type
    return Agent(**kwargs)
