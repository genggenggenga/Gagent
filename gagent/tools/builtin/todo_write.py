"""Built-in todo planning tool."""

from __future__ import annotations

import ast
import json
from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult

VALID_TODO_STATUS = {"pending", "in_progress", "completed"}


def todo_write_tool() -> RegisteredTool:
    return RegisteredTool(
        name="todo_write",
        description=(
            "Create or replace the current task progress list. "
            "Use this before multi-step work and update statuses as work progresses."
        ),
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Ordered task progress list for the current user request.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Concrete task step.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Current task status.",
                            },
                        },
                        "required": ["content", "status"],
                    },
                }
            },
            "required": ["todos"],
        },
        runner=_todo_write,
        category="read",
        risk_level="low",
    )


def _todo_write(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    del context
    todos, error = normalize_todos(args.get("todos"))
    if error:
        return ToolResult(content=error, is_error=True)

    counts = todo_counts(todos)
    content = render_todos(todos)
    return ToolResult(
        content=f"{content}\n\nUpdated {len(todos)} todos.",
        metadata={
            "todos": todos,
            "todo_counts": counts,
        },
    )


def normalize_todos(raw_todos: Any) -> tuple[list[dict[str, str]], str | None]:
    todos = raw_todos
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return [], "error: todos must be a list or JSON array string"

    if not isinstance(todos, list):
        return [], "error: todos must be a list"

    normalized: list[dict[str, str]] = []
    in_progress_count = 0
    for index, todo in enumerate(todos):
        if not isinstance(todo, dict):
            return [], f"error: todos[{index}] must be an object"
        content = str(todo.get("content", "")).strip()
        status = str(todo.get("status", "")).strip()
        if not content:
            return [], f"error: todos[{index}] missing 'content'"
        if status not in VALID_TODO_STATUS:
            valid = ", ".join(sorted(VALID_TODO_STATUS))
            return [], f"error: todos[{index}] status must be one of {valid}"
        if status == "in_progress":
            in_progress_count += 1
        normalized.append({"content": content, "status": status})

    if in_progress_count > 1:
        return [], "error: only one todo can be in_progress at a time"
    return normalized, None


def todo_counts(todos: list[dict[str, str]]) -> dict[str, int]:
    return {status: sum(1 for todo in todos if todo["status"] == status) for status in sorted(VALID_TODO_STATUS)}


def render_todos(todos: list[dict[str, str]]) -> str:
    if not todos:
        return "Current todos: empty"

    icon_by_status = {
        "pending": "[ ]",
        "in_progress": "[>]",
        "completed": "[x]",
    }
    lines = ["Current todos:"]
    for index, todo in enumerate(todos, start=1):
        icon = icon_by_status[todo["status"]]
        lines.append(f"{index}. {icon} {todo['content']}")
    return "\n".join(lines)
