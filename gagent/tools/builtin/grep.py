"""Built-in grep-style text search tool."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult
from gagent.tools.builtin.write_file import resolve_workspace_path

_SKIP_DIRS = {".git", ".gagent", ".venv", "__pycache__", "node_modules"}


def grep_tool() -> RegisteredTool:
    return RegisteredTool(
        name="grep",
        description=(
            "Search workspace file contents with a regex pattern. "
            "Returns matching lines with file paths and line numbers."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {
                    "type": "string",
                    "description": "Workspace-relative directory or file path.",
                    "default": ".",
                },
                "include": {
                    "type": "string",
                    "description": "Optional glob filter for files, such as '*.py'.",
                },
                "literal": {
                    "type": "boolean",
                    "description": "Treat pattern as literal text instead of regex.",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return.",
                    "default": 100,
                },
            },
            "required": ["pattern"],
        },
        runner=_grep,
        category="read",
        risk_level="low",
    )


def _grep(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    pattern = str(args.get("pattern", ""))
    if not pattern:
        return ToolResult(content="error: pattern is required", is_error=True)

    raw_path = str(args.get("path") or ".")
    path = resolve_workspace_path(context.cwd, raw_path)
    if not path.exists():
        return ToolResult(content=f"error: path does not exist: {raw_path}", is_error=True)

    include = args.get("include")
    include_pattern = str(include) if include else None
    literal = bool(args.get("literal", False))
    limit = _positive_int(args.get("limit", 100), default=100, maximum=1000)

    if shutil.which("rg"):
        return _grep_with_rg(
            pattern=pattern,
            root=context.cwd.resolve(),
            path=path,
            include=include_pattern,
            literal=literal,
            limit=limit,
        )
    return _grep_with_python(
        pattern=pattern,
        root=context.cwd.resolve(),
        path=path,
        include=include_pattern,
        literal=literal,
        limit=limit,
    )


def _grep_with_rg(
    *,
    pattern: str,
    root: Path,
    path: Path,
    include: str | None,
    literal: bool,
    limit: int,
) -> ToolResult:
    target = path.resolve().relative_to(root).as_posix() if path.resolve() != root else "."
    command = ["rg", "-n", "--smart-case"]
    if literal:
        command.append("-F")
    if include:
        command.extend(["--glob", include])
    for skipped in sorted(_SKIP_DIRS):
        command.extend(["--glob", f"!{skipped}/**"])
    command.extend(["--", pattern, target])

    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode > 1:
        return ToolResult(content=(result.stderr.strip() or "error: grep failed"), is_error=True)

    lines = result.stdout.splitlines()
    matches = lines[:limit]
    content = "\n".join(matches)
    if len(lines) > limit:
        content += f"\n... (stopped at limit {limit})"
    return ToolResult(
        content=content or "(no matches)",
        metadata={"engine": "rg", "matches": min(len(lines), limit), "truncated": len(lines) > limit},
    )


def _grep_with_python(
    *,
    pattern: str,
    root: Path,
    path: Path,
    include: str | None,
    literal: bool,
    limit: int,
) -> ToolResult:
    regex = None
    if not literal:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(content=f"error: invalid regex: {exc}", is_error=True)

    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    matches: list[str] = []
    for file_path in files:
        if _should_skip(file_path) or _is_binary(file_path):
            continue
        rel_path = file_path.resolve().relative_to(root).as_posix()
        if include and not _matches_include(rel_path, include):
            continue
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            found = pattern in line if literal else regex is not None and regex.search(line)
            if not found:
                continue
            matches.append(f"{rel_path}:{line_no}: {line}")
            if len(matches) >= limit:
                return ToolResult(
                    content="\n".join(matches) + f"\n... (stopped at limit {limit})",
                    metadata={"engine": "python", "matches": len(matches), "truncated": True},
                )
    return ToolResult(
        content="\n".join(matches) or "(no matches)",
        metadata={"engine": "python", "matches": len(matches), "truncated": False},
    )


def _matches_include(rel_path: str, include: str) -> bool:
    return fnmatch.fnmatch(rel_path, include) or fnmatch.fnmatch(Path(rel_path).name, include)


def _is_binary(path: Path) -> bool:
    try:
        return b"\x00" in path.read_bytes()[:512]
    except OSError:
        return True


def _should_skip(path: Path) -> bool:
    return bool(set(path.parts) & _SKIP_DIRS)


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))
