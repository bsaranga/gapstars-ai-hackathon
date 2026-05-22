from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from .pipeline import screen

app = typer.Typer(add_completion=False, help="Multi-agent CV screening.")


def _read(path: Path) -> str:
    if not path.exists():
        raise typer.BadParameter(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev)."),
) -> None:
    """Launch the web visualizer (http://HOST:PORT)."""
    import uvicorn

    uvicorn.run(
        "cv_screener.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def run(
    cv: Path = typer.Option(..., "--cv", help="Path to the candidate's CV (text)."),
    jd: Path = typer.Option(..., "--jd", help="Path to the job description (text)."),
    out: Path | None = typer.Option(
        None, "--out", help="Write full JSON result to this file."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Print every specialist output, not just the recommendation."
    ),
) -> None:
    """Screen a CV against a job description (CLI mode)."""
    raw_cv = _read(cv)
    raw_jd = _read(jd)

    result = asyncio.run(screen(raw_cv, raw_jd))
    payload = result.to_dict()

    if out:
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        typer.echo(f"wrote {out}")

    rec = result.recommendation
    typer.echo("")
    typer.echo(f"Recommendation : {rec.recommendation.upper()}")
    typer.echo(f"Overall score  : {rec.overall_score}/100")
    typer.echo("")
    typer.echo("Strengths:")
    for s in rec.strengths:
        typer.echo(f"  - {s}")
    typer.echo("Concerns:")
    for c in rec.concerns:
        typer.echo(f"  - {c}")
    if rec.red_flags:
        typer.echo("Red flags:")
        for f in rec.red_flags:
            typer.echo(f"  - {f}")
    typer.echo("Suggested interview questions:")
    for q in rec.suggested_interview_questions:
        typer.echo(f"  - {q}")
    typer.echo("")
    typer.echo(f"Rationale: {rec.rationale}")

    if verbose:
        typer.echo("")
        typer.echo("--- specialist outputs ---")
        for key in ("skills", "experience", "education", "red_flags", "communication"):
            typer.echo(f"\n[{key}]")
            typer.echo(json.dumps(payload[key], indent=2))


if __name__ == "__main__":
    app()
