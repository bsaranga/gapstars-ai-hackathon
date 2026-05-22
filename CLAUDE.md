# CLAUDE.md

Working notes for Claude Code in this repo.

## What this repo is

A **bug-triage AI workflow** — design phase. The authoritative spec is
[`docs/bug_triage_design.md`](docs/bug_triage_design.md). Read it before
making non-trivial changes; it covers the architecture, schemas, prompts,
tool signatures, error handling, observability, and recommended build
order. README.md is a summary, not the spec.

The pipeline is: **Orchestrator → Analyzer (Agent 1) → Completeness Gate →
Triage (Agent 2) → Artifact Generator (Agent 3, stretch)**.

## Invariants — do not violate without updating the design doc first

- **Completeness Gate lives in the orchestrator (§4.4), not inside Triage.**
  When `analysis.completeness.verdict == "needs_more_info"`, Triage must
  not be invoked — no tool calls, no LLM spend, no severity/priority
  fields on the response.
- **Severity/priority rules are deterministic first (§5.3).** The LLM is
  only the residual fallback. `rule_applied` must be populated.
- **Triage never receives `teams.json` / `tasks.json` in its prompt.** It
  uses the two tools in §5.7 (`get_team_members`,
  `get_developer_history`). Tool-call budget: 1 + 3 per bug, enforced by
  the orchestrator.
- **`suggested_assignee.reason` must cite signals from tool output** —
  matched skills and/or specific task ids. Reasons without citations are
  rejected and fall back to the deterministic scorer.
- **Notification list is built by the orchestrator (§5.6)**, not the
  agent — from `stakeholder.notify_on` plus the team's
  `escalation_contact_id` for P0.
- **Configs are Pydantic-validated at boot (§5.6, §5.8).** Boot must fail
  loudly on duplicate ids, unknown areas, unresolved cross-references.
- **Tools are pure reads.** Any write (recording an assignment back to
  `tasks.json`, etc.) happens in Agent 3 or the orchestrator, never in a
  tool exposed to Agent 2.
- **Fallback path stays alive.** If the Triage model lacks function
  calling, the deterministic skills-only scorer must take over (§7, §11).

## Layout

```
docs/bug_triage_design.md   # source of truth — keep in sync with code
config/                     # (planned) teams.json, tasks.json
src/                        # orchestrator + agents (in progress)
examples/                   # fixture bug reports (planned)
```

## Conventions

- Use **Pydantic models** for every inter-agent payload and every config
  file. No free-form dict passing across agent boundaries.
- Log every tool call (args + result hash), every gate short-circuit,
  every rule-vs-LLM decision, and every fallback (§8.3).
- New severity/priority rules go in the rules table (§5.3) with a unit
  test, not in agent prompts.
- New `affected_area` values must be added to the §4.2 enum *and* be
  representable in `teams.json` `areas` arrays — boot validation catches
  drift.

## When working on this repo

- Implementation tracks the build order in §11. Don't skip steps that
  earlier ones depend on (e.g. the gate before Triage, the rules module
  before the agent).
- When adding a fixture bug report, also label it with expected severity,
  priority, team, and assignee so it can join the evaluation set (§12).
- Pyproject still names the package `cv-screener` from an earlier
  iteration; rename when the orchestrator entrypoint lands.
