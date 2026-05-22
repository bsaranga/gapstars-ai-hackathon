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
from ..prompts import load_prompt
from ._factory import make_agent

_PROMPT, PROMPT_VERSION = load_prompt("triage")

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
