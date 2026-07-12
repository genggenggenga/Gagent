"""Runtime hook primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

HookPoint = Literal[
    "before_turn",
    "before_model",
    "after_model",
    "before_tool",
    "after_tool",
    "before_final",
]


@dataclass(frozen=True)
class HookContext:
    """Context passed to runtime hooks."""

    runtime: Any
    point: HookPoint
    payload: dict[str, Any]


@dataclass(frozen=True)
class HookResult:
    """Hook outcome. A denied result short-circuits the current action."""

    allowed: bool = True
    reason: str = "hook_ok"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, reason: str = "hook_ok") -> "HookResult":
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(
        cls,
        reason: str,
        *,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> "HookResult":
        return cls(
            allowed=False,
            reason=reason,
            message=message,
            metadata=metadata or {},
        )


RuntimeHook = Callable[[HookContext], HookResult | None]


@dataclass(frozen=True)
class RegisteredHook:
    point: HookPoint
    hook: RuntimeHook
    name: str
    mandatory: bool = False


class HookManager:
    """Synchronous hook registry used by the runtime."""

    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[RegisteredHook]] = {
            "before_turn": [],
            "before_model": [],
            "after_model": [],
            "before_tool": [],
            "after_tool": [],
            "before_final": [],
        }

    def register(
        self,
        point: HookPoint,
        hook: RuntimeHook,
        *,
        name: str | None = None,
        mandatory: bool = False,
    ) -> None:
        self._hooks[point].append(
            RegisteredHook(
                point=point,
                hook=hook,
                name=name or getattr(hook, "__name__", hook.__class__.__name__),
                mandatory=mandatory,
            )
        )

    def run(self, point: HookPoint, context: HookContext) -> HookResult:
        for registered in self._hooks[point]:
            result = registered.hook(context) or HookResult.allow()
            if not result.allowed:
                return result
        return HookResult.allow()

    def names_for(self, point: HookPoint) -> list[str]:
        return [hook.name for hook in self._hooks[point]]
