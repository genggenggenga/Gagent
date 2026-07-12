"""Built-in directory listing tool."""

from pathlib import Path
from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult
from gagent.tools.builtin.write_file import resolve_workspace_path


def list_dir_tool() -> RegisteredTool:
    return RegisteredTool(
        name="list_dir",
        description="List files and directories under a workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative directory path.",
                    "default": ".",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries to return.",
                    "default": 200,
                },
            },
        },
        runner=_list_dir,
        category="read",
        risk_level="low",
    )


def _list_dir(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    raw_path = str(args.get("path") or ".")
    path = resolve_workspace_path(context, raw_path)
    if not path.is_dir():
        return ToolResult(content=f"error: path is not a directory: {raw_path}", is_error=True)

    limit = _positive_int(args.get("limit", 200), default=200, maximum=1000)
    entries = sorted(path.iterdir(), key=_sort_key)
    rendered = [_render_entry(entry) for entry in entries[:limit]]
    if len(entries) > limit:
        rendered.append(f"... ({len(entries) - limit} more entries)")
    return ToolResult(content="\n".join(rendered) or "(empty directory)")


def _render_entry(path: Path) -> str:
    suffix = "/" if path.is_dir() else ""
    return f"{path.name}{suffix}"


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))
