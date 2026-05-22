from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from .agents import analyzer_agent, artifact_agent, parse_bug, triage_agent
from .config import TriageDeps, load_all
from .models import (
    AnalysisOutput,
    ArtifactBundle,
    BugReport,
    FinalReport,
    NotifyContact,
    TriageDecision,
)
from .rules import build_notify_list, classify, select_team


@dataclass
class TriageResult:
    bug: BugReport
    analysis: AnalysisOutput
    decision: TriageDecision | None
    artifacts: ArtifactBundle | None
    final: FinalReport

    def to_dict(self) -> dict:
        return {
            "bug": self.bug.model_dump(),
            "analysis": self.analysis.model_dump(),
            "decision": self.decision.model_dump() if self.decision else None,
            "artifacts": self.artifacts.model_dump() if self.artifacts else None,
            "final": self.final.model_dump(),
        }


def _new_bug_id() -> str:
    return f"BUG-{uuid.uuid4().hex[:10].upper()}"


async def triage(raw_markdown: str, deps: TriageDeps | None = None) -> TriageResult:
    """Run the full bug-triage pipeline.

    parse → analyzer → completeness gate → deterministic rules + team
    lookup → triage agent (with tools) → notify list → artifact agent.
    """
    deps = deps or load_all()

    bug = await parse_bug(raw_markdown)
    if not bug.bug_id:
        bug = bug.model_copy(update={"bug_id": _new_bug_id()})

    analysis_result = await analyzer_agent.run(json.dumps(bug.model_dump()))
    analysis: AnalysisOutput = analysis_result.output

    # Completeness Gate (§4.4) — short-circuit before any triage spend.
    if analysis.completeness.verdict == "needs_more_info":
        final = FinalReport(
            bug_id=bug.bug_id or "",
            summary=analysis.summary,
            status="Needs More Information",
            missing_information=analysis.missing_information,
            blocking_fields=analysis.completeness.blocking_fields,
            suggested_repro_steps=analysis.inferred_repro_steps,
            rationale=analysis.completeness.rationale,
        )
        return TriageResult(
            bug=bug, analysis=analysis, decision=None, artifacts=None, final=final
        )

    verdict = classify(bug, analysis, deps.rules)
    team = select_team(analysis, deps.teams)

    triage_input = json.dumps(
        {
            "analysis": analysis.model_dump(),
            "severity": verdict.severity,
            "priority": verdict.priority,
            "team_id": team.id,
        }
    )
    decision_result = await triage_agent.run(triage_input, deps=deps)
    decision: TriageDecision = decision_result.output

    notify_raw = build_notify_list(team, verdict.priority)
    notify = [NotifyContact(**n) for n in notify_raw]

    artifact_input = json.dumps(
        {
            "bug": bug.model_dump(),
            "analysis": analysis.model_dump(),
            "severity": verdict.severity,
            "priority": verdict.priority,
            "rule_id": verdict.rule_id,
            "team_name": team.name,
            "jira_project": team.jira_project,
            "slack_channel": team.slack_channel,
            "assignee": decision.suggested_assignee.model_dump(
                include={"id", "name"}
            ),
            "notify": [n.model_dump() for n in notify],
        }
    )
    artifact_result = await artifact_agent.run(artifact_input, deps=deps)
    artifacts: ArtifactBundle = artifact_result.output

    final = FinalReport(
        bug_id=bug.bug_id or "",
        summary=analysis.summary,
        status="Triaged",
        severity=verdict.severity,
        priority=verdict.priority,
        missing_information=analysis.missing_information,
        suggested_repro_steps=analysis.inferred_repro_steps or bug.steps_to_reproduce,
        suggested_owner_team=team.name,
        suggested_assignee=decision.suggested_assignee,
        notify=notify,
        triage_recommendation=decision.triage_recommendation,
        rule_applied=(
            f"{verdict.rule_id}: {verdict.rule_applied} → "
            f"{verdict.severity} / {verdict.priority}"
        ),
        artifacts=artifacts,
    )
    return TriageResult(
        bug=bug, analysis=analysis, decision=decision, artifacts=artifacts, final=final
    )
