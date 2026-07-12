"""Built-in file writing tool."""

from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult


def write_file_tool() -> RegisteredTool:
    return RegisteredTool(
        name="write_file",
        description="Write UTF-8 text content to a workspace file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Content to write."},
            },
            "required": ["path", "content"],
        },
        runner=_write_file,
        category="write",
        risk_level="high",
    )


def _write_file(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    raw_path = str(args.get("path", ""))
    path = context.resolve_path(raw_path)
    if path.exists() and path.is_dir():
        return ToolResult(content=f"error: path is a directory: {raw_path}", is_error=True)

    content = str(args.get("content", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    byte_count = len(content.encode("utf-8"))
    return ToolResult(
        content=f"wrote {byte_count} bytes to {raw_path}",
        metadata={"path": raw_path, "bytes": byte_count},
    )


def resolve_workspace_path(context: ToolExecutionContext, raw_path: str):
    """Compatibility wrapper for built-in tools that still import this helper."""

    return context.resolve_path(raw_path)
