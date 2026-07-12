"""Run artifact storage for per-turn observation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gagent.core.task_state import TaskState


class RunStore:
    """Persist artifacts for each user request."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, task_state: TaskState) -> Path:
        return self.root / task_state.run_id

    def task_state_path(self, task_state: TaskState) -> Path:
        return self.run_dir(task_state) / "task_state.json"

    def trace_path(self, task_state: TaskState) -> Path:
        return self.run_dir(task_state) / "trace.jsonl"

    def report_path(self, task_state: TaskState) -> Path:
        return self.run_dir(task_state) / "report.json"

    def artifacts_dir(self, task_state: TaskState) -> Path:
        return self.run_dir(task_state) / "artifacts"

    def start_run(self, task_state: TaskState) -> Path:
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir(task_state).mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state: TaskState) -> Path:
        path = self.task_state_path(task_state)
        self._write_json_atomic(path, task_state.to_dict())
        return path

    def append_trace(self, task_state: TaskState, event: dict[str, Any]) -> Path:
        path = self.trace_path(task_state)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            file.write("\n")
        return path

    def write_report(self, task_state: TaskState, report: dict[str, Any]) -> Path:
        path = self.report_path(task_state)
        self._write_json_atomic(path, report)
        return path

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
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
