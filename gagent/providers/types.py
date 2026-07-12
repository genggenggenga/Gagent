"""Provider request and response types."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Message = dict[str, Any]
ToolSchema = dict[str, Any]
StopReason = Literal["stop", "tool_calls", "length", "content_filter", "error", "unknown"]
TextSink = Callable[[str], None]


@dataclass(frozen=True)
class ToolCall:
    """A normalized model request to execute a tool."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderUsage:
    """Best-effort token and cost usage reported by a provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class ChatCompletionResult:
    """A normalized model completion returned by provider implementations."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: ProviderUsage | None = None
    stop_reason: StopReason = "unknown"
    raw_stop_reason: str = ""
