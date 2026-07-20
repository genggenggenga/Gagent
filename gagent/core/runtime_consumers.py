"""Consumers that derive runtime state from emitted events."""

from __future__ import annotations

from typing import Any, Protocol

from gagent.core.task_state import TaskState


class RuntimeConsumer(Protocol):
    def handle(self, runtime: Any, task_state: TaskState, event: dict[str, Any]) -> None:
        """Consume one normalized runtime event."""


class DecisionReminderConsumer:
    """Collect denied policy/permission decisions for later model reminders."""

    def handle(self, runtime: Any, task_state: TaskState, event: dict[str, Any]) -> None:
        if event.get("event") not in {"tool_policy_decision", "permission_decision"}:
            return
        if event.get("decision") != "deny":
            return
        task_state.runtime_reminders.append(
            {
                "event": event.get("event", ""),
                "tool_name": event.get("tool_name", ""),
                "reason": event.get("reason", ""),
                "message": event.get("message", ""),
                "created_at": event.get("created_at", ""),
            }
        )


class ToolStatsConsumer:
    """Track simple tool success/error counters."""

    def handle(self, runtime: Any, task_state: TaskState, event: dict[str, Any]) -> None:
        if event.get("event") != "tool_finished":
            return
        tool_name = str(event.get("tool_name", ""))
        if not tool_name:
            return
        stats = task_state.tool_stats.setdefault(
            tool_name,
            {"calls": 0, "errors": 0, "duration_ms": 0},
        )
        stats["calls"] = int(stats.get("calls", 0)) + 1
        stats["duration_ms"] = int(stats.get("duration_ms", 0)) + int(
            event.get("duration_ms", 0) or 0
        )
        if event.get("is_error"):
            stats["errors"] = int(stats.get("errors", 0)) + 1


class ChangedPathConsumer:
    """Track paths changed by successful write tools."""

    def handle(self, runtime: Any, task_state: TaskState, event: dict[str, Any]) -> None:
        if event.get("event") != "tool_finished" or event.get("is_error"):
            return
        if event.get("tool_name") not in {"edit_file", "write_file"}:
            return
        metadata = event.get("metadata") or {}
        path = str(metadata.get("path") or "")
        if path and path not in task_state.changed_paths:
            task_state.changed_paths.append(path)


class TodoStateConsumer:
    """Keep the current todo list in task state."""

    def handle(self, runtime: Any, task_state: TaskState, event: dict[str, Any]) -> None:
        if event.get("event") != "tool_finished" or event.get("is_error"):
            return
        if event.get("tool_name") != "todo_write":
            return
        metadata = event.get("metadata") or {}
        todos = metadata.get("todos")
        if not isinstance(todos, list):
            return
        normalized = [dict(todo) for todo in todos if isinstance(todo, dict)]
        task_state.todos = normalized
        task_state.todo_changes.append(
            {
                "action": "write",
                "todos": normalized,
                "counts": dict(metadata.get("todo_counts") or {}),
                "created_at": event.get("created_at", ""),
            }
        )


def default_runtime_consumers() -> list[RuntimeConsumer]:
    return [
        DecisionReminderConsumer(),
        ToolStatsConsumer(),
        ChangedPathConsumer(),
        TodoStateConsumer(),
    ]
