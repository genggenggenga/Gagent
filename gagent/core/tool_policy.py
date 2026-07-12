"""Tool usage policy checks above raw permission gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from gagent.tools.base import RegisteredTool, ToolExecutionContext

SHELL_SEARCH_RE = re.compile(
    r"(?:^|;|&&|\|\|)\s*(?:cat|less|head|tail|grep|rg|find|ls)(?:\s|$)"
)


@dataclass(frozen=True)
class ToolPolicyDecision:
    """Decision for whether a tool call is a good use of that tool."""

    decision: Literal["allow", "deny"]
    reason: str
    message: str = ""

    @classmethod
    def allow(cls, reason: str = "policy_ok") -> "ToolPolicyDecision":
        return cls("allow", reason)

    @classmethod
    def deny(cls, reason: str, message: str) -> "ToolPolicyDecision":
        return cls("deny", reason, message)

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


class ToolPolicyChecker:
    """Guardrails that steer the model toward the right tool behavior."""

    def __init__(self) -> None:
        self.fresh_reads: set[Path] = set()
        self.recent_mutations: set[tuple[str, str]] = set()

    def check(
        self,
        tool: RegisteredTool,
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        if tool.name == "bash":
            return self._check_bash(args)
        if tool.name == "edit_file":
            return self._requires_fresh_read(tool.name, args, context)
        if tool.name == "write_file":
            path = _resolve_optional_path(args, context)
            if path is not None and path.exists() and path.is_file():
                return self._requires_fresh_read(tool.name, args, context)
        if tool.category == "write":
            mutation_key = _mutation_key(tool.name, args)
            if mutation_key in self.recent_mutations:
                return ToolPolicyDecision.deny(
                    "repeated_identical_call",
                    f"error: repeated identical {tool.name} call blocked",
                )
        return ToolPolicyDecision.allow()

    def record_result(
        self,
        tool: RegisteredTool,
        args: dict[str, Any],
        context: ToolExecutionContext,
        *,
        is_error: bool,
    ) -> None:
        if is_error:
            return
        path = _resolve_optional_path(args, context)
        if tool.name == "read_file" and path is not None:
            self.fresh_reads.add(path)
        if tool.category == "write":
            self.recent_mutations.add(_mutation_key(tool.name, args))

    def _check_bash(self, args: dict[str, Any]) -> ToolPolicyDecision:
        command = str(args.get("command", "")).strip()
        if SHELL_SEARCH_RE.search(command):
            return ToolPolicyDecision.deny(
                "shell_search_should_use_tool",
                (
                    "error: bash is not for ordinary workspace search/read; "
                    "use grep, glob, list_dir, or read_file first"
                ),
            )
        return ToolPolicyDecision.allow()

    def _requires_fresh_read(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        path = _resolve_optional_path(args, context)
        if path is not None and path in self.fresh_reads:
            return ToolPolicyDecision.allow()
        return ToolPolicyDecision.deny(
            "prior_read_required",
            f"error: {tool_name} requires a fresh read_file of {args.get('path', '')} first",
        )


def _resolve_optional_path(args: dict[str, Any], context: ToolExecutionContext) -> Path | None:
    raw_path = str(args.get("path") or "")
    if not raw_path:
        return None
    try:
        return context.resolve_path(raw_path)
    except ValueError:
        return None


def _mutation_key(tool_name: str, args: dict[str, Any]) -> tuple[str, str]:
    return (tool_name, repr(sorted(args.items())))
