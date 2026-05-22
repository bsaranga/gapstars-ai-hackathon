from dotenv import load_dotenv

load_dotenv()

from bug_triage.pipeline import TriageResult, triage  # noqa: E402

__all__ = ["triage", "TriageResult"]
