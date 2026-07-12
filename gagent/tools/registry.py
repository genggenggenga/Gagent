"""Tool registration and lookup."""

from dataclasses import dataclass
from typing import Any

from gagent.tools.base import RegisteredTool, ToolExecutionContext, ToolResult
from gagent.tools.builtin.bash import bash_tool
from gagent.tools.builtin.read_file import read_file_tool
from gagent.tools.builtin.write_file import write_file_tool


@dataclass(frozen=True)
class ToolProfile:
    """A named view over the full tool registry."""

    name: str
    allowed_tools: frozenset[str]

    def allows(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools


class ToolRegistry:
    """Explicit allowlist of tools available to the agent."""

    def __init__(self, tools: list[RegisteredTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools_for_profile(self, profile: ToolProfile) -> list[RegisteredTool]:
        return [tool for tool in self._tools.values() if profile.allows(tool.name)]

    def schemas_for_profile(self, profile: ToolProfile) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self.tools_for_profile(profile)]

    def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolExecutionContext,
        profile: ToolProfile,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(content=f"error: unknown tool '{name}'", is_error=True)
        if not profile.allows(name):
            return ToolResult(
                content=f"error: tool '{name}' is not allowed in profile '{profile.name}'",
                is_error=True,
            )
        return tool.execute(args, context)


def build_builtin_registry() -> ToolRegistry:
    return ToolRegistry([bash_tool(), read_file_tool(), write_file_tool()])


def build_tool_profiles(registry: ToolRegistry) -> dict[str, ToolProfile]:
    names = frozenset(registry.names())
    read_only = frozenset(
        name for name in names if (tool := registry.get(name)) is not None and tool.read_only
    )
    return {
        "default": ToolProfile("default", names),
        "readonly": ToolProfile("readonly", read_only),
        "no_shell": ToolProfile("no_shell", names - frozenset({"bash"})),
    }


def resolve_tool_profile(registry: ToolRegistry, name: str) -> ToolProfile:
    profiles = build_tool_profiles(registry)
    try:
        return profiles[name]
    except KeyError as exc:
        available = ", ".join(sorted(profiles))
        raise ValueError(f"unknown tool profile '{name}', available: {available}") from exc
