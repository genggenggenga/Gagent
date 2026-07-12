"""Built-in shell execution tool."""

import subprocess
from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult

_DANGEROUS_COMMAND_PARTS = (
    "rm -rf /",
    "sudo ",
    "shutdown",
    "reboot",
    "> /dev/",
)


def bash_tool() -> RegisteredTool:
    return RegisteredTool(
        name="bash",
        description="Run a shell command in the current workspace.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute."},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.",
                    "default": 120,
                },
            },
            "required": ["command"],
        },
        runner=_run_bash,
        category="execute",
        risk_level="high",
    )


def _run_bash(args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    command = str(args.get("command", "")).strip()
    if not command:
        return ToolResult(content="error: command is required", is_error=True)
    if any(part in command for part in _DANGEROUS_COMMAND_PARTS):
        return ToolResult(content="error: dangerous command blocked", is_error=True)

    timeout = int(args.get("timeout", 120))
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=context.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(content=f"error: timeout after {timeout}s", is_error=True)
    except OSError as exc:
        return ToolResult(content=f"error: {exc}", is_error=True)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    content = "\n".join(
        [
            f"exit_code: {result.returncode}",
            "stdout:",
            _clip_output(stdout) if stdout else "(empty)",
            "stderr:",
            _clip_output(stderr) if stderr else "(empty)",
        ]
    )
    return ToolResult(
        content=content,
        is_error=result.returncode != 0,
        metadata={
            "exit_code": result.returncode,
            "stdout_chars": len(result.stdout),
            "stderr_chars": len(result.stderr),
        },
    )


def _clip_output(text: str, limit: int = 50000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 24] + "\n... (output truncated)"
