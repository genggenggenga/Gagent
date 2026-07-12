"""Per-turn runtime state for observation and debugging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


def now_iso() -> str:
    """Return an ISO timestamp suitable for JSONL records."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class TaskState:
    """Mutable state for a single user request."""

    run_id: str
    turn_id: str
    user_request: str
    status: str = "running"
    stop_reason: str = ""
    attempts: int = 0
    tool_steps: int = 0
    last_tool: str = ""
    final_text: str = ""
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def create(cls, user_request: str) -> "TaskState":
        suffix = uuid4().hex[:8]
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return cls(
            run_id=f"run_{timestamp}_{suffix}",
            turn_id=f"turn_{timestamp}_{suffix}",
            user_request=user_request,
            started_at=now_iso(),
        )

    def record_attempt(self) -> None:
        self.attempts += 1

    def record_tool(self, name: str) -> None:
        self.tool_steps += 1
        self.last_tool = name

    def finish(self, *, status: str, stop_reason: str, final_text: str = "") -> None:
        self.status = status
        self.stop_reason = stop_reason
        self.final_text = final_text
        self.finished_at = now_iso()

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "user_request": self.user_request,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempts": self.attempts,
            "tool_steps": self.tool_steps,
            "last_tool": self.last_tool,
            "final_text": self.final_text,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
