"""Built-in file reading tool."""

from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult
from gagent.tools.builtin.write_file import resolve_workspace_path


def read_file_tool() -> RegisteredTool:
    return RegisteredTool(
        name="read_file",
        description="Read a UTF-8 text file from the workspace by line range.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "start": {"type": "integer", "description": "1-based start line.", "default": 1},
                "end": {"type": "integer", "description": "Inclusive end line.", "default": 200},
            },
            "required": ["path"],
        },
        runner=_read_file,
        category="read",
        risk_level="low",
    )


def _read_file(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    path = resolve_workspace_path(context, str(args.get("path", "")))
    if not path.is_file():
        return ToolResult(content=f"error: path is not a file: {args.get('path', '')}", is_error=True)

    start = int(args.get("start", 1))
    end = int(args.get("end", 200))
    if start < 1 or end < start:
        return ToolResult(content="error: invalid line range", is_error=True)

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    selected = lines[start - 1 : end]
    prefix_width = len(str(min(end, len(lines)))) if lines else 1
    content = "\n".join(
        f"{line_no:>{prefix_width}} | {line}"
        for line_no, line in enumerate(selected, start=start)
    )
    if end < len(lines):
        content += f"\n... ({len(lines) - end} more lines)"
    return ToolResult(content=content or "(empty file)")
