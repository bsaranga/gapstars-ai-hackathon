from __future__ import annotations

from pydantic_ai import RunContext

from ..config import (
    DeveloperNotFound,
    TeamNotFound,
    TriageDeps,
    get_developer_history_impl,
    get_team_members_impl,
)
from ..models import (
    AffectedArea,
    DeveloperSummary,
    TaskSummary,
    TriageDecision,
)
from ._factory import make_agent

_PROMPT = """You are the Triage Agent. Severity, priority, and the owner
team have ALREADY been decided deterministically by the orchestrator. Your
only job is to pick the single best `suggested_assignee` from the chosen
team's roster and write a one-sentence `triage_recommendation`.

INPUT (a JSON object):
- `analysis`: the AnalysisOutput (summary, affected_area,
  extracted_errors, ...).
- `severity`, `priority`: the final values chosen by the orchestrator.
- `team_id`: the team to pick an assignee from.

TOOLS AVAILABLE
- `get_team_members(team_id)` — call ONCE. Returns the team's roster as
  DeveloperSummary objects (id, name, skills, seniority, on_call,
  availability, open_load).
- `get_developer_history(developer_id, area=...)` — call for the 2-3
  most plausible candidates only. Returns recent TaskSummary records.

BUDGET: at most 1 get_team_members call and 3 get_developer_history calls
per bug. Stay within budget.

SELECTION ALGORITHM
1. Call get_team_members(team_id) once.
2. Score candidates by overlap of `skills` with `analysis.affected_area`
   and tokens from `analysis.extracted_errors`.
3. For each of the top 2-3, call get_developer_history(id,
   area=analysis.affected_area) to confirm track record.
4. Pick the best. Tie-breakers, in order:
   (a) `on_call == true` is preferred for priority == "P0";
   (b) demonstrated recent resolution of similar tasks (cite ids);
   (c) shorter `resolution_time_hours` on comparable severity;
   (d) higher `seniority` for P0/P1, lower for P2/P3 so juniors get
       growth tickets;
   (e) prefer lower `open_load` — 3 open tasks = loaded, 5+ = overloaded.
5. `availability == "out"` developers are already filtered out by the
   tool; do NOT try to bypass with include_unavailable.

OUTPUT FIELDS
- `suggested_assignee.id` / `.name` — must match a developer returned by
  the tool. NEVER invent an id.
- `suggested_assignee.reason` — MUST cite the specific signals you used:
  the matched skills AND at least one task id from get_developer_history
  when relevant. Generic reasons ("looks experienced") are rejected by
  the orchestrator.
- `triage_recommendation` — one sentence: who to assign, why, and what
  the impact looks like.

OUTPUT: valid JSON only, matching the TriageDecision schema.
"""

triage_agent = make_agent(
    "triage",
    output_type=TriageDecision,
    system_prompt=_PROMPT,
    deps_type=TriageDeps,
)


@triage_agent.tool
def get_team_members(
    ctx: RunContext[TriageDeps],
    team_id: str,
    include_unavailable: bool = False,
) -> list[DeveloperSummary]:
    """Return developers on `team_id`.

    By default, developers with availability == "out" are excluded.
    Raises TeamNotFound if the team_id is unknown.
    """
    try:
        return get_team_members_impl(ctx.deps, team_id, include_unavailable)
    except TeamNotFound as e:
        raise ValueError(str(e)) from e


@triage_agent.tool
def get_developer_history(
    ctx: RunContext[TriageDeps],
    developer_id: str,
    area: AffectedArea | None = None,
    limit: int = 10,
    since_days: int = 365,
) -> list[TaskSummary]:
    """Return up to `limit` tasks resolved by `developer_id`.

    Filters:
      - area: if set, only tasks whose `area` matches.
      - since_days: only tasks within this window.
    Ordering: most recent first.
    Raises DeveloperNotFound if the developer_id is unknown.
    """
    try:
        return get_developer_history_impl(
            ctx.deps, developer_id, area=area, limit=limit, since_days=since_days
        )
    except DeveloperNotFound as e:
        raise ValueError(str(e)) from e
