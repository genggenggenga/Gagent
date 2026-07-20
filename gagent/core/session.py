"""Persistent session data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SESSION_SCHEMA_VERSION = 1


def now_iso() -> str:
    """Return an ISO timestamp suitable for persisted session records."""

    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class SessionState:
    """Serializable conversation state that can be resumed later."""

    id: str
    created_at: str
    updated_at: str
    workspace: dict[str, str]
    model: str
    system_prompt_hash: str
    messages: list[dict[str, Any]]
    todos: list[dict[str, str]] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    schema_version: int = SESSION_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        workspace: dict[str, str],
        model: str,
        system_prompt_hash: str,
        messages: list[dict[str, Any]],
    ) -> "SessionState":
        created_at = now_iso()
        return cls(
            id=session_id,
            created_at=created_at,
            updated_at=created_at,
            workspace=dict(workspace),
            model=model,
            system_prompt_hash=system_prompt_hash,
            messages=[dict(message) for message in messages],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionState":
        schema_version = int(payload.get("schema_version", 0) or 0)
        if schema_version != SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported session schema version: {schema_version}")

        session_id = str(payload.get("id", "")).strip()
        if not session_id:
            raise ValueError("session is missing id")

        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise ValueError("session messages must be a list")

        todos = payload.get("todos", [])
        run_ids = payload.get("run_ids", [])
        workspace = payload.get("workspace", {})

        return cls(
            id=session_id,
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
            workspace=dict(workspace) if isinstance(workspace, dict) else {},
            model=str(payload.get("model", "")),
            system_prompt_hash=str(payload.get("system_prompt_hash", "")),
            messages=[dict(message) for message in messages if isinstance(message, dict)],
            todos=[dict(todo) for todo in todos if isinstance(todo, dict)],
            run_ids=[str(run_id) for run_id in run_ids if str(run_id).strip()],
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workspace": dict(self.workspace),
            "model": self.model,
            "system_prompt_hash": self.system_prompt_hash,
            "messages": [dict(message) for message in self.messages],
            "todos": [dict(todo) for todo in self.todos],
            "run_ids": list(self.run_ids),
        }

    def touch(self) -> None:
        self.updated_at = now_iso()
