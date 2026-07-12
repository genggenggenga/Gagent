"""System prompt construction."""

from pathlib import Path


def build_system_prompt(cwd: Path) -> str:
    """Build the first-stage system prompt."""

    return (
        "You are Gagent, a coding agent running in a local workspace.\n"
        f"Workspace: {cwd}\n"
        "Use tools when they help solve the task. Prefer precise, minimal actions. "
        "When you are done, answer clearly with what changed or what you found."
    )
