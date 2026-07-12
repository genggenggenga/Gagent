"""Session-level JSONL event bus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from gagent.core.task_state import now_iso

Redactor = Callable[[dict[str, Any]], dict[str, Any]]


class SessionEventBus:
    """Append coarse-grained session events to a JSONL file."""

    def __init__(
        self,
        *,
        session_id: str,
        path: Path,
        redact: Redactor | None = None,
    ) -> None:
        self.session_id = session_id
        self.path = Path(path)
        self.redact = redact or (lambda record: record)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        record = dict(payload or {})
        record["event"] = event
        record["session_id"] = self.session_id
        record["created_at"] = now_iso()
        record = self.redact(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            file.write("\n")
        return record
