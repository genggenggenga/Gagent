"""Session JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gagent.core.session import SessionState


class SessionStore:
    """Persist resumable conversation state under `.gagent/sessions`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        return self.root / f"{_safe_session_id(session_id)}.json"

    def event_path(self, session_id: str) -> Path:
        return self.root / f"{_safe_session_id(session_id)}.events.jsonl"

    def save(self, session: SessionState) -> Path:
        session.touch()
        path = self.path(session.id)
        _write_json_atomic(path, session.to_dict())
        return path

    def load(self, session_id: str) -> SessionState:
        path = self.path(session_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"session not found: {session_id}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"session is not valid JSON: {session_id}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"session payload must be an object: {session_id}")
        return SessionState.from_dict(payload)

    def latest(self) -> str | None:
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        files = sorted(
            self.root.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            try:
                session = self.load(path.stem)
            except ValueError:
                continue
            rows.append(
                {
                    "id": session.id,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "message_count": len(session.messages),
                    "run_count": len(session.run_ids),
                    "model": session.model,
                    "workspace_root": session.workspace.get("repo_root", ""),
                    "last_user_message": _last_user_message(session.messages),
                }
            )
        return rows


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, path)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _clip(str(message.get("content", "")), 80)
    return ""


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _safe_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("invalid session id")
    return value
