from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .models import (
    AffectedArea,
    DeveloperSummary,
    TaskSummary,
    TasksConfig,
    TeamsConfig,
)

_DEFAULT_TEAMS_PATH = Path("config/teams.json")
_DEFAULT_TASKS_PATH = Path("config/tasks.json")


def _resolve(env: str, default: Path) -> Path:
    raw = os.getenv(env)
    return Path(raw) if raw else default


def load_teams(path: Path | None = None) -> TeamsConfig:
    p = path or _resolve("BUG_TRIAGE_TEAMS_FILE", _DEFAULT_TEAMS_PATH)
    return TeamsConfig.model_validate_json(p.read_text(encoding="utf-8"))


def load_tasks(path: Path | None = None) -> TasksConfig:
    p = path or _resolve("BUG_TRIAGE_TASKS_FILE", _DEFAULT_TASKS_PATH)
    return TasksConfig.model_validate_json(p.read_text(encoding="utf-8"))


def open_tasks_per_developer(tasks: TasksConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tasks.tasks:
        if t.status == "in_progress":
            counts[t.assignee_id] = counts.get(t.assignee_id, 0) + 1
    return counts


@dataclass
class TriageDeps:
    """Runtime dependencies injected into the Triage Agent via RunContext.

    Only the fields the tools actually need; PII is filtered out at the
    tool boundary (see DeveloperSummary).
    """

    teams: TeamsConfig
    tasks: TasksConfig
    open_load: dict[str, int] = field(default_factory=dict)


# ---------- Tool implementations (pure reads) ----------


class TeamNotFound(LookupError):
    pass


class DeveloperNotFound(LookupError):
    pass


def get_team_members_impl(
    deps: TriageDeps, team_id: str, include_unavailable: bool = False
) -> list[DeveloperSummary]:
    team = deps.teams.get_team(team_id)
    if team is None:
        raise TeamNotFound(f"unknown team_id: {team_id!r}")
    out: list[DeveloperSummary] = []
    for d in team.developers:
        if not include_unavailable and d.availability == "out":
            continue
        out.append(
            DeveloperSummary(
                id=d.id,
                name=d.name,
                role=d.role,
                skills=d.skills,
                seniority=d.seniority,
                on_call=d.on_call,
                availability=d.availability,
                open_load=deps.open_load.get(d.id, 0),
            )
        )
    return out


def get_developer_history_impl(
    deps: TriageDeps,
    developer_id: str,
    area: AffectedArea | None = None,
    limit: int = 10,
    since_days: int = 365,
) -> list[TaskSummary]:
    dev_ids = {d.id for t in deps.teams.teams for d in t.developers}
    if developer_id not in dev_ids:
        raise DeveloperNotFound(f"unknown developer_id: {developer_id!r}")

    cutoff = date.today() - timedelta(days=since_days)
    rows: list[tuple[str, TaskSummary]] = []
    for t in deps.tasks.tasks:
        if t.assignee_id != developer_id:
            continue
        if area is not None and t.area != area:
            continue
        if t.resolved_at:
            try:
                if date.fromisoformat(t.resolved_at) < cutoff:
                    continue
            except ValueError:
                pass
        rows.append(
            (
                t.resolved_at or t.opened_at,
                TaskSummary(
                    id=t.id,
                    type=t.type,
                    title=t.title,
                    area=t.area,
                    severity=t.severity,
                    priority=t.priority,
                    status=t.status,
                    tags=t.tags,
                    resolved_at=t.resolved_at,
                    resolution_time_hours=t.resolution_time_hours,
                    outcome_rating=t.outcome_rating,
                ),
            )
        )
    rows.sort(key=lambda r: r[0], reverse=True)
    return [s for _, s in rows[:limit]]


def load_all(
    teams_path: Path | None = None, tasks_path: Path | None = None
) -> TriageDeps:
    teams = load_teams(teams_path)
    tasks = load_tasks(tasks_path)
    tasks.cross_validate(teams)
    return TriageDeps(
        teams=teams, tasks=tasks, open_load=open_tasks_per_developer(tasks)
    )


__all__ = [
    "TriageDeps",
    "TeamNotFound",
    "DeveloperNotFound",
    "load_teams",
    "load_tasks",
    "load_all",
    "open_tasks_per_developer",
    "get_team_members_impl",
    "get_developer_history_impl",
]
