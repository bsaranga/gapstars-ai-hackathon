from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Literal

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

Role = Literal["parser", "specialist", "aggregator"]

# Default model per role. Strings use LiteLLM-style provider prefixes:
#   together_ai/<model>      → Together AI (needs TOGETHER_API_KEY)
#   openai/<model>           → OpenAI       (needs OPENAI_API_KEY)
#   anthropic/<model>        → Anthropic    (needs ANTHROPIC_API_KEY)
# Override per role with CV_SCREENER_MODEL_{PARSER,SPECIALIST,AGGREGATOR}.
_DEFAULT_BY_ROLE: dict[Role, str] = {
    "parser":     "together_ai/openai/gpt-oss-20b",
    "specialist": "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "aggregator": "together_ai/openai/gpt-oss-20b",
}
_ENV_BY_ROLE: dict[Role, str] = {
    "parser":     "CV_SCREENER_MODEL_PARSER",
    "specialist": "CV_SCREENER_MODEL_SPECIALIST",
    "aggregator": "CV_SCREENER_MODEL_AGGREGATOR",
}


def _build_model(model_string: str) -> Model:
    """Map a LiteLLM-style 'provider/model' string to a pydantic-ai Model.

    The first '/' separates the provider prefix from the (possibly slash-
    containing) model name, e.g. ``together_ai/meta-llama/Llama-3.3-70B``.
    """
    if "/" not in model_string:
        # bare model name → assume OpenAI
        provider_prefix, model_name = "openai", model_string
    else:
        provider_prefix, model_name = model_string.split("/", 1)
    provider_prefix = provider_prefix.lower()

    if provider_prefix in ("together_ai", "togetherai", "together"):
        key = os.getenv("TOGETHER_API_KEY")
        if not key:
            raise RuntimeError("TOGETHER_API_KEY is not set.")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(
                base_url="https://api.together.xyz/v1", api_key=key
            ),
        )

    if provider_prefix == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return OpenAIChatModel(
            model_name, provider=OpenAIProvider(api_key=key)
        )

    if provider_prefix == "anthropic":
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider
        except ImportError as e:
            raise RuntimeError(
                "Anthropic support not installed. `pip install anthropic`."
            ) from e
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        return AnthropicModel(model_name, provider=AnthropicProvider(api_key=key))

    if provider_prefix in ("gemini", "google"):
        try:
            from pydantic_ai.models.gemini import GeminiModel
            from pydantic_ai.providers.google_gla import GoogleGLAProvider
        except ImportError as e:
            raise RuntimeError(
                "Gemini support not installed."
            ) from e
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
        return GeminiModel(model_name, provider=GoogleGLAProvider(api_key=key))

    raise RuntimeError(
        f"Unknown model provider prefix: {provider_prefix!r} "
        f"(model string was {model_string!r}). "
        f"Supported: together_ai/, openai/, anthropic/, gemini/."
    )


def _model_for(role: Role) -> Model:
    return _build_model(os.getenv(_ENV_BY_ROLE[role], _DEFAULT_BY_ROLE[role]))


def make_agent(
    role: Role,
    *,
    output_type,
    system_prompt: str,
    tools: Sequence[Any] = (),
) -> Agent:
    # When tools are present, force serial tool use: the model must pick a
    # tool OR the final answer per turn, not both. Without this, pydantic-ai
    # short-circuits on the first final_result it sees and silently drops the
    # parallel tool calls, so the agent never actually reads tool results.
    settings = (
        ModelSettings(parallel_tool_calls=False) if tools else ModelSettings()
    )
    return Agent(
        model=_model_for(role),
        output_type=output_type,
        system_prompt=system_prompt,
        retries=2,
        tools=list(tools),
        model_settings=settings,
    )
