"""Base provider interface for model calls."""

from typing import Protocol

from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolSchema


class Provider(Protocol):
    """Abstract model provider consumed by the agent loop."""

    model: str

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        """Send a chat request and return one normalized completion result."""
        ...
