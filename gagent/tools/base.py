"""Base tool contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from gagent.core.workspace import WorkspaceContext

RiskLevel = Literal["low", "medium", "high"]
ToolCategory = Literal["read", "write", "execute"]


@dataclass(frozen=True)
class ToolExecutionContext:
    """Runtime context passed to tool implementations."""

    cwd: Path
    workspace: WorkspaceContext | None = None

    def resolve_path(self, raw_path: str) -> Path:
        if self.workspace is not None:
            return self.workspace.resolve_path(raw_path)
        return _resolve_cwd_path(self.cwd, raw_path)

    def relative_path(self, path: Path) -> str:
        if self.workspace is not None:
            return self.workspace.relative_to_root(path)
        return path.resolve().relative_to(self.cwd.resolve()).as_posix()


def _resolve_cwd_path(cwd: Path, raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("path is required")
    root = cwd.resolve()
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes workspace: {raw_path}")
    return path


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""

    content: str
    is_error: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegisteredTool:
    """A tool that can be exposed to a model."""

    name: str
    description: str
    parameters: dict[str, Any]
    runner: Callable[[dict[str, Any], ToolExecutionContext], ToolResult | str]
    category: ToolCategory
    risk_level: RiskLevel = "low"

    @property
    def read_only(self) -> bool:
        return self.category == "read"

    @property
    def risky(self) -> bool:
        return self.risk_level == "high"

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, args: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        try:
            result = self.runner(args, context)
        except Exception as exc:
            return ToolResult(content=f"error: tool {self.name} failed: {exc}", is_error=True)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(content=str(result))
