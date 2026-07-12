"""System prompt construction."""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime

from gagent.core.workspace import WorkspaceContext
from gagent.tools.registry import ToolProfile, ToolRegistry


@dataclass(frozen=True)
class SystemPrompt:
    """Rendered system prompt plus signatures for future cache decisions."""

    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    built_at: str


def build_system_prompt(
    *,
    workspace: WorkspaceContext,
    tools: ToolRegistry,
    profile: ToolProfile,
    built_at: str | None = None,
) -> SystemPrompt:
    """Build the system prompt from real runtime context."""

    tool_text = _tool_guidance(tools, profile)
    text = textwrap.dedent(
        f"""\
        You are Gagent, a local coding agent working inside a real project workspace.

        ## Operating Rules

        - Use tools when they help verify the workspace, inspect code, or make changes.
        - Prefer precise, minimal actions that match the existing project style.
        - Read files before modifying existing code.
        - Use `grep` for content search, `glob` for file discovery, and `read_file` for context.
        - Do not use `bash` for ordinary workspace search or file reading.
        - Use `edit_file` for targeted modifications; use `write_file` for new files or full rewrites.
        - Before `edit_file` or overwriting an existing file with `write_file`, read the target file first.
        - Do not invent tool results, file contents, command output, or real-time facts.
        - Keep all file operations inside the workspace boundary.
        - When finished, answer clearly with what changed or what you found.

        ## Available Tool Guidance

        Tool profile: {profile.name}
        {tool_text}

        {workspace.to_prompt_section()}
        """
    ).strip()
    workspace_fingerprint = workspace.fingerprint()
    signature = tool_signature(tools, profile)
    return SystemPrompt(
        text=text,
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        workspace_fingerprint=workspace_fingerprint,
        tool_signature=signature,
        built_at=built_at or datetime.now(UTC).isoformat(),
    )


def tool_signature(tools: ToolRegistry, profile: ToolProfile) -> str:
    payload = []
    for tool in sorted(tools.tools_for_profile(profile), key=lambda item: item.name):
        payload.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "category": tool.category,
                "risk_level": tool.risk_level,
            }
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _tool_guidance(tools: ToolRegistry, profile: ToolProfile) -> str:
    lines = []
    for tool in sorted(tools.tools_for_profile(profile), key=lambda item: item.name):
        lines.append(
            f"- `{tool.name}` [{tool.category}, risk={tool.risk_level}]: {tool.description}"
        )
    return "\n".join(lines) or "- none"
