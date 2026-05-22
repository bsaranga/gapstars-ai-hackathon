from __future__ import annotations

from pydantic_ai import RunContext

from ..config import TriageDeps, get_triage_rules_impl
from ..models import ArtifactBundle, TriageRuleSummary
from ._factory import make_agent

_PROMPT = """You are the Artifact Generator. You produce engineering
handoff artifacts for a triaged bug.

INPUT (a JSON object) keys:
- `bug`: the parsed BugReport
- `analysis`: the AnalysisOutput
- `severity`, `priority`: chosen by the deterministic rule table
- `rule_id`: the id of the rule that fired (e.g. "auth-broken")
- `team_name`, `jira_project`, `slack_channel`
- `assignee`: {id, name}
- `notify`: [{id, name, role}, ...]

REQUIRED FIRST STEP — call the `get_triage_rules` tool ONCE to fetch the
full rule table, then find the rule whose `id` matches `rule_id`. You
must use its `description` and `notes` when writing the handoff_note and
the Description block in the Jira ticket. Never invent rule descriptions
that don't appear in the tool's output.

THEN produce:
1. `jira_ticket`: a multi-line Jira-style ticket block with these fields
   in this order:
     - Title (prefixed with [<jira_project>] if provided)
     - Type: Bug
     - Severity (must equal the input `severity`)
     - Priority (must equal the input `priority`)
     - Rule applied: "<rule_id> — <rule.description>"   ← cite the tool result
     - Component
     - Assignee
     - CC (comma-separated names from `notify`)
     - Environment
     - Description (analysis.summary + actual vs expected)
     - Steps (numbered, from analysis.inferred_repro_steps OR
       bug.steps_to_reproduce).
2. `test_cases`: 2-4 concise test case strings covering the failure path
   AND adjacent regressions (other browsers, edge inputs).
3. `duplicate_check_query`: a search string suitable for Jira/GitHub
   search — distinctive quoted tokens combined with AND.
4. `handoff_note`: 3-5 sentences for the on-call engineer. Must:
     - Open with the chosen severity & priority and the rule that
       drove the classification (the description from the tool result).
     - Say what is broken and where to look first.
     - End with one sentence on what to verify.
   Posted to the team's `slack_channel`.

OUTPUT: valid JSON only, matching the ArtifactBundle schema. Do not
include any prose outside the JSON.
"""

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
