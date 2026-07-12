"""Runtime permission decisions for tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from gagent.tools.base import RegisteredTool, ToolExecutionContext
from gagent.tools.registry import ToolProfile

ApprovalPolicy = Literal["auto", "never"]


@dataclass(frozen=True)
class PermissionDecision:
    """Decision for whether a tool call may execute now."""

    decision: Literal["allow", "deny"]
    reason: str
    security_event_type: str = ""
    message: str = ""

    @classmethod
    def allow(cls, reason: str) -> "PermissionDecision":
        return cls("allow", reason)

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        security_event_type: str = "",
        message: str = "",
    ) -> "PermissionDecision":
        return cls("deny", reason, security_event_type, message)

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


class PermissionChecker:
    """Default gate between model-requested tool calls and execution."""

    def __init__(self, *, approval_policy: ApprovalPolicy = "auto") -> None:
        if approval_policy not in {"auto", "never"}:
            raise ValueError("approval_policy must be 'auto' or 'never'")
        self.approval_policy: ApprovalPolicy = approval_policy

    def check(
        self,
        tool: RegisteredTool,
        args: dict[str, Any],
        context: ToolExecutionContext,
        profile: ToolProfile,
    ) -> PermissionDecision:
        if not profile.allows(tool.name):
            return PermissionDecision.deny(
                "tool_not_allowed",
                security_event_type="tool_profile_block",
                message=f"error: tool '{tool.name}' is not allowed in profile '{profile.name}'",
            )
        path_decision = self._check_workspace_path(tool, args, context)
        if path_decision is not None:
            return path_decision
        if tool.read_only:
            return PermissionDecision.allow("read_only")
        if self.approval_policy == "never":
            return PermissionDecision.deny(
                "approval_denied",
                security_event_type="approval_denied",
                message=f"error: approval denied for {tool.name}",
            )
        return PermissionDecision.allow("approval_auto")

    def _check_workspace_path(
        self,
        tool: RegisteredTool,
        args: dict[str, Any],
        context: ToolExecutionContext,
    ) -> PermissionDecision | None:
        if tool.category not in {"read", "write"}:
            return None
        raw_path = str(args.get("path") or args.get("pattern") or "")
        if not raw_path:
            return None
        if tool.name == "glob":
            return None
        try:
            context.resolve_path(raw_path)
        except ValueError as exc:
            return PermissionDecision.deny(
                "workspace_path_escape",
                security_event_type="workspace_path_guard",
                message=f"error: {exc}",
            )
        return None
