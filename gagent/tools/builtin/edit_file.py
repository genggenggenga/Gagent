"""Built-in exact text replacement tool."""

from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult
from gagent.tools.builtin.write_file import resolve_workspace_path


def edit_file_tool() -> RegisteredTool:
    return RegisteredTool(
        name="edit_file",
        description="Replace one exact text occurrence in a UTF-8 workspace file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "old_text": {"type": "string", "description": "Exact text to replace."},
                "new_text": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_text", "new_text"],
        },
        runner=_edit_file,
        category="write",
        risk_level="medium",
    )


def _edit_file(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    raw_path = str(args.get("path", ""))
    path = resolve_workspace_path(context, raw_path)
    if not path.is_file():
        return ToolResult(content=f"error: path is not a file: {raw_path}", is_error=True)

    old_text = str(args.get("old_text", ""))
    new_text = str(args.get("new_text", ""))
    if not old_text:
        return ToolResult(content="error: old_text is required", is_error=True)

    content = path.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_text)
    if count == 0:
        return ToolResult(content=f"error: old_text not found in {raw_path}", is_error=True)
    if count > 1:
        return ToolResult(
            content=(
                f"error: old_text occurs {count} times in {raw_path}; "
                "provide a larger unique snippet"
            ),
            is_error=True,
        )

    updated = content.replace(old_text, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    delta = len(updated.encode("utf-8")) - len(content.encode("utf-8"))
    return ToolResult(
        content=f"edited {raw_path} (1 replacement, byte_delta: {delta})",
        metadata={"path": raw_path, "replacements": 1, "byte_delta": delta},
    )
