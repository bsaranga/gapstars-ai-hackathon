from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AnalysisOutput,
    BugReport,
    Priority,
    Severity,
    Team,
    TeamsConfig,
    TriageRule,
    TriageRulesConfig,
)


@dataclass(frozen=True)
class RuleVerdict:
    severity: Severity
    priority: Priority
    rule_applied: str
    rule_id: str


def _haystack(bug: BugReport, analysis: AnalysisOutput) -> str:
    """Lowercased text used for keyword matching."""
    return " ".join(
        [
            bug.title,
            bug.description,
            bug.actual_result or "",
            analysis.summary,
            " ".join(analysis.extracted_errors),
        ]
    ).lower()


def _env_haystack(bug: BugReport, text: str) -> str:
    env = bug.environment
    return " ".join(
        [
            env.app_version or "",
            env.os or "",
            env.browser or "",
            env.device or "",
            env.user_role or "",
            text,
        ]
    ).lower()


def _matches(rule: TriageRule, bug: BugReport, analysis: AnalysisOutput) -> bool:
    m = rule.match
    text = _haystack(bug, analysis)
    if m.any_keywords and not any(k.lower() in text for k in m.any_keywords):
        return False
    if m.all_keywords and not all(k.lower() in text for k in m.all_keywords):
        return False
    if m.exclude_keywords and any(k.lower() in text for k in m.exclude_keywords):
        return False
    if m.affected_areas and analysis.affected_area not in m.affected_areas:
        return False
    if m.environment_substrings:
        env_text = _env_haystack(bug, text)
        if not any(s.lower() in env_text for s in m.environment_substrings):
            return False
    return True


def classify(
    bug: BugReport, analysis: AnalysisOutput, rules: TriageRulesConfig
) -> RuleVerdict:
    """Apply the rule table in order; first match wins.

    The rule table's loader guarantees a catch-all default at the end, so
    this function always returns a verdict.
    """
    for r in rules.rules:
        if _matches(r, bug, analysis):
            return RuleVerdict(
                severity=r.severity,
                priority=r.priority,
                rule_applied=r.description,
                rule_id=r.id,
            )
    raise RuntimeError(
        "no rule matched — TriageRulesConfig validator should have prevented this"
    )


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
