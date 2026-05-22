from __future__ import annotations

from dataclasses import dataclass

from .models import AnalysisOutput, BugReport, Priority, Severity, Team, TeamsConfig

_OUTAGE_KEYWORDS = (
    "outage",
    "down",
    "cannot access",
    "all users",
    "data loss",
    "security breach",
    " 500",
    " 502",
    " 503",
)
_COSMETIC_KEYWORDS = ("alignment", "color", "typo", "padding", "spacing")
_FUNCTIONAL_VERBS = ("cannot", "fails", "crashes", "broken", "error")


@dataclass(frozen=True)
class RuleVerdict:
    severity: Severity
    priority: Priority
    rule_applied: str


def _haystack(bug: BugReport, analysis: AnalysisOutput) -> str:
    parts = [
        bug.title,
        bug.description,
        bug.actual_result or "",
        analysis.summary,
        " ".join(analysis.extracted_errors),
    ]
    return " ".join(parts).lower()


def _is_production_outage(bug: BugReport, analysis: AnalysisOutput) -> bool:
    text = _haystack(bug, analysis)
    has_keyword = any(k in text for k in _OUTAGE_KEYWORDS)
    in_prod = (bug.environment.app_version or "").lower().startswith(
        ("prod", "production")
    ) or "production" in text
    return has_keyword and in_prod


def _is_cosmetic(bug: BugReport, analysis: AnalysisOutput) -> bool:
    text = _haystack(bug, analysis)
    has_cosmetic = any(k in text for k in _COSMETIC_KEYWORDS)
    has_functional = any(v in text for v in _FUNCTIONAL_VERBS)
    return has_cosmetic and not has_functional


def classify(bug: BugReport, analysis: AnalysisOutput) -> RuleVerdict:
    """Deterministic severity/priority from §5.3. Run before any LLM call."""
    if _is_production_outage(bug, analysis):
        return RuleVerdict("Critical", "P0", "Production outage / data loss / security")
    if analysis.affected_area in ("auth", "payments"):
        return RuleVerdict("High", "P1", "Auth / Payment issue")
    if _is_cosmetic(bug, analysis):
        return RuleVerdict("Low", "P3", "UI cosmetic")
    return RuleVerdict("Medium", "P2", "Default (workaround likely exists)")


def select_team(analysis: AnalysisOutput, teams: TeamsConfig) -> Team:
    team = teams.find_team_for_area(analysis.affected_area)
    if team is None:
        raise RuntimeError(
            f"No team owns area={analysis.affected_area!r} and no "
            "triage_lead_team_id configured."
        )
    return team


def build_notify_list(team: Team, priority: Priority) -> list[dict]:
    notify: list[dict] = []
    seen: set[str] = set()
    for s in team.stakeholders:
        if priority in s.notify_on and s.id not in seen:
            seen.add(s.id)
            notify.append({"id": s.id, "name": s.name, "role": s.role})
    if priority == "P0" and team.escalation_contact_id:
        if team.escalation_contact_id not in seen:
            for s in team.stakeholders:
                if s.id == team.escalation_contact_id:
                    notify.append({"id": s.id, "name": s.name, "role": s.role})
                    seen.add(s.id)
                    break
    return notify
