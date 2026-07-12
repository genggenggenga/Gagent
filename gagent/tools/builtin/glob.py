"""Built-in glob search tool."""

from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult


def glob_tool() -> RegisteredTool:
    return RegisteredTool(
        name="glob",
        description="Find workspace files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern relative to the workspace, such as '**/*.py'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return.",
                    "default": 200,
                },
            },
            "required": ["pattern"],
        },
        runner=_glob,
        category="read",
        risk_level="low",
    )


def _glob(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        return ToolResult(content="error: pattern is required", is_error=True)
    if pattern.startswith("/") or ".." in pattern.split("/"):
        return ToolResult(content=f"error: invalid workspace glob pattern: {pattern}", is_error=True)

    limit = _positive_int(args.get("limit", 200), default=200, maximum=1000)
    root = context.cwd.resolve()
    matches = []
    for path in sorted(root.glob(pattern)):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        if resolved.is_dir():
            continue
        matches.append(resolved.relative_to(root).as_posix())
        if len(matches) >= limit:
            break

    total_hint = "" if len(matches) < limit else f"\n... (stopped at limit {limit})"
    return ToolResult(content=("\n".join(matches) + total_hint).strip() or "(no matches)")


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))
