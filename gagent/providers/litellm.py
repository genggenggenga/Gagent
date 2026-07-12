"""LiteLLM-backed provider implementation."""

import json
from typing import Any

import litellm
from litellm import completion, completion_cost, token_counter

from gagent.providers.types import (
    ChatCompletionResult,
    Message,
    ProviderUsage,
    StopReason,
    TextSink,
    ToolCall,
    ToolSchema,
)

litellm.suppress_debug_info = True


class LiteLLMProvider:
    """LiteLLM-backed provider implementation.

    The rest of Gagent depends on normalized completion results, not LiteLLM's
    chunks or response objects. This keeps the core loop free from
    provider-specific streaming and finish-reason parsing details.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
        timeout: int = 300,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.temperature,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        if stream:
            return self._streaming(messages, kwargs, on_text=on_text)

        return self._non_streaming(kwargs, on_text=on_text)

    def _streaming(
        self,
        messages: list[Message],
        kwargs: dict[str, Any],
        *,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        response = completion(**kwargs)
        full_text = ""
        tool_calls_by_index: dict[int, dict[str, Any]] = {}
        raw_stop_reason = ""

        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                raw_stop_reason = str(finish_reason)

            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                full_text += content
                if on_text:
                    on_text(content)

            for tool_delta in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(tool_delta, "index", 0) or 0)
                entry = tool_calls_by_index.setdefault(
                    index,
                    {"id": "", "function": {"name": "", "arguments": ""}},
                )
                tool_id = getattr(tool_delta, "id", None)
                if tool_id:
                    entry["id"] = tool_id
                function = getattr(tool_delta, "function", None)
                if function is None:
                    continue
                name = getattr(function, "name", None)
                arguments = getattr(function, "arguments", None)
                if name:
                    entry["function"]["name"] += name
                if arguments:
                    entry["function"]["arguments"] += arguments

        tool_calls = tuple(
            _tool_call_from_raw(tool_calls_by_index[index])
            for index in sorted(tool_calls_by_index)
        )
        usage = self._estimate_streaming_usage(messages, full_text)
        return ChatCompletionResult(
            text=full_text,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=_normalize_stop_reason(raw_stop_reason, has_tool_calls=bool(tool_calls)),
            raw_stop_reason=raw_stop_reason,
        )

    def _non_streaming(
        self,
        kwargs: dict[str, Any],
        *,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        kwargs = dict(kwargs)
        kwargs["stream"] = False
        response = completion(**kwargs)
        choice = response.choices[0]
        message = choice.message

        text = message.content or ""
        if text and on_text:
            on_text(text)

        tool_calls = tuple(
            _tool_call_from_litellm(call) for call in (message.tool_calls or ())
        )
        provider_usage = None
        usage = getattr(response, "usage", None)
        if usage:
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            cost = _completion_cost(response)
            provider_usage = self._record_usage(input_tokens, output_tokens, cost)

        raw_stop_reason = str(getattr(choice, "finish_reason", "") or "")
        return ChatCompletionResult(
            text=text,
            tool_calls=tool_calls,
            usage=provider_usage,
            stop_reason=_normalize_stop_reason(raw_stop_reason, has_tool_calls=bool(tool_calls)),
            raw_stop_reason=raw_stop_reason,
        )

    def _estimate_streaming_usage(
        self,
        messages: list[Message],
        output_text: str,
    ) -> ProviderUsage | None:
        try:
            input_tokens = int(token_counter(model=self.model, messages=messages))
            output_tokens = int(token_counter(model=self.model, text=output_text))
        except Exception:
            return None

        try:
            cost = float(
                completion_cost(
                    model=self.model,
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                )
            )
        except Exception:
            cost = 0.0
        return self._record_usage(input_tokens, output_tokens, cost)

    def _record_usage(self, input_tokens: int, output_tokens: int, cost: float) -> ProviderUsage:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        return ProviderUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost=cost)

    @property
    def usage_summary(self) -> str:
        total_tokens = self.total_input_tokens + self.total_output_tokens
        parts = [f"tokens: {total_tokens:,}"]
        if self.total_cost > 0:
            parts.append(f"cost: ${self.total_cost:.4f}")
        return " | ".join(parts)


def _tool_call_from_raw(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function", {})
    return ToolCall(
        id=str(raw.get("id") or ""),
        name=str(function.get("name") or ""),
        arguments=_parse_arguments(function.get("arguments", "")),
    )


def _tool_call_from_litellm(raw: Any) -> ToolCall:
    function = raw.function
    return ToolCall(
        id=str(raw.id or ""),
        name=str(function.name or ""),
        arguments=_parse_arguments(function.arguments or ""),
    )


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _completion_cost(response: Any) -> float:
    try:
        return float(completion_cost(response))
    except Exception:
        return 0.0


def _normalize_stop_reason(raw_stop_reason: str, *, has_tool_calls: bool) -> StopReason:
    if has_tool_calls:
        return "tool_calls"

    normalized = raw_stop_reason.lower()
    if normalized in {"stop", "end_turn"}:
        return "stop"
    if normalized in {"tool_calls", "function_call"}:
        return "tool_calls"
    if normalized in {"length", "max_tokens", "max_output_tokens"}:
        return "length"
    if normalized in {"content_filter", "safety"}:
        return "content_filter"
    if normalized in {"error"}:
        return "error"
    return "unknown"
