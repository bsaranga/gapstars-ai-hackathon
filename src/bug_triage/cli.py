from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from .config import load_all
from .pipeline import triage as run_triage

app = typer.Typer(add_completion=False, help="Multi-agent bug triage.")


def _read(path: Path) -> str:
    if not path.exists():
        raise typer.BadParameter(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev)."),
) -> None:
    """Launch the web UI (http://HOST:PORT)."""
    import uvicorn

    uvicorn.run(
        "bug_triage.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def triage(
    bug: Path = typer.Option(..., "--bug", help="Markdown file with the bug report."),
    teams: Path | None = typer.Option(
        None, "--teams", help="Override path to teams.json (default: config/teams.json)."
    ),
    tasks: Path | None = typer.Option(
        None, "--tasks", help="Override path to tasks.json (default: config/tasks.json)."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Write full JSON result to this file."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Print every agent output, not just the final report."
    ),
) -> None:
    """Triage a bug report from a markdown file."""
    raw = _read(bug)
    deps = load_all(teams_path=teams, tasks_path=tasks)
    result = asyncio.run(run_triage(raw, deps=deps))
    payload = result.to_dict()

    if out:
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        typer.echo(f"wrote {out}")

    final = result.final
    typer.echo("")
    typer.echo(f"Bug ID         : {final.bug_id}")
    typer.echo(f"Status         : {final.status}")
    if final.status == "Needs More Information":
        typer.echo(f"Rationale      : {final.rationale}")
        typer.echo("Blocking fields:")
        for b in final.blocking_fields:
            typer.echo(f"  - {b}")
        return

    typer.echo(f"Severity       : {final.severity}")
    typer.echo(f"Priority       : {final.priority}")
    typer.echo(f"Rule applied   : {final.rule_applied}")
    typer.echo(f"Owner team     : {final.suggested_owner_team}")
    if final.suggested_assignee:
        typer.echo(
            f"Assignee       : {final.suggested_assignee.name} "
            f"({final.suggested_assignee.id})"
        )
        typer.echo(f"  Reason       : {final.suggested_assignee.reason}")
    if final.notify:
        typer.echo("Notify:")
        for n in final.notify:
            typer.echo(f"  - {n.name} ({n.role})")
    typer.echo("")
    typer.echo(f"Recommendation : {final.triage_recommendation}")

    if verbose and final.artifacts:
        typer.echo("")
        typer.echo("--- artifacts ---")
        typer.echo("\n[jira_ticket]")
        typer.echo(final.artifacts.jira_ticket)
        typer.echo("\n[test_cases]")
        for tc in final.artifacts.test_cases:
            typer.echo(f"  - {tc}")
        typer.echo(f"\n[duplicate_check_query] {final.artifacts.duplicate_check_query}")
        typer.echo("\n[handoff_note]")
        typer.echo(final.artifacts.handoff_note)


if __name__ == "__main__":
    app()
