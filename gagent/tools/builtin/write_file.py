"""Built-in file writing tool."""

from pathlib import Path
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
    path = resolve_workspace_path(context.cwd, raw_path)
    if path.exists() and path.is_dir():
        return ToolResult(content=f"error: path is a directory: {raw_path}", is_error=True)

    content = str(args.get("content", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return ToolResult(content=f"wrote {len(content.encode('utf-8'))} bytes to {raw_path}")


def resolve_workspace_path(cwd: Path, raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("path is required")
    root = cwd.resolve()
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {raw_path}")
    return path
