from __future__ import annotations

from pydantic_ai import RunContext

from ..config import TriageDeps, get_triage_rules_impl
from ..models import ArtifactBundle, TriageRuleSummary
from ..prompts import load_prompt
from ._factory import make_agent

_PROMPT, PROMPT_VERSION = load_prompt("artifact")

artifact_agent = make_agent(
    "artifact",
    output_type=ArtifactBundle,
    system_prompt=_PROMPT,
    deps_type=TriageDeps,
)


@artifact_agent.tool
def get_triage_rules(ctx: RunContext[TriageDeps]) -> list[TriageRuleSummary]:
    """Return the full severity/priority rule table from rules.json.

    Use to confirm the rule that the orchestrator applied (matched by
    `rule_id` in the agent's input) so the artifacts can cite its
    description and notes.
    """
    return get_triage_rules_impl(ctx.deps)
