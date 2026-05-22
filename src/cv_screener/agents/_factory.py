from __future__ import annotations

import os
from typing import Literal

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

Role = Literal["parser", "specialist", "aggregator"]

_DEFAULT_MODEL = "openai/gpt-oss-20b"
_ENV_BY_ROLE: dict[Role, str] = {
    "parser": "CV_SCREENER_MODEL_PARSER",
    "specialist": "CV_SCREENER_MODEL_SPECIALIST",
    "aggregator": "CV_SCREENER_MODEL_AGGREGATOR",
}


def _together_model(role: Role) -> OpenAIChatModel:
    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TOGETHER_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    model_name = os.getenv(_ENV_BY_ROLE[role], _DEFAULT_MODEL)
    provider = OpenAIProvider(
        base_url="https://api.together.xyz/v1",
        api_key=api_key,
    )
    return OpenAIChatModel(model_name, provider=provider)


def make_agent(role: Role, *, output_type, system_prompt: str) -> Agent:
    return Agent(
        model=_together_model(role),
        output_type=output_type,
        system_prompt=system_prompt,
        retries=2,
    )
