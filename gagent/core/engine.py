"""Turn-level runtime engine.

Runtime owns state and dependencies. Engine owns the control loop that turns
one user request into model calls, tool executions, and final output.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from gagent.core.messages import assistant_message, tool_message, user_message as build_user_message
from gagent.core.task_state import TaskState
from gagent.providers.types import ChatCompletionResult, Message, ProviderUsage

TextSink = Callable[[str], None]


@dataclass(frozen=True)
class AgentRunResult:
    """Result returned after one user request finishes."""

    final_text: str
    messages: list[Message]
    steps: int
    usage: ProviderUsage | None = None
    hit_step_limit: bool = False
    stop_reason: str = "stop"
    run_id: str = ""
    turn_id: str = ""
    tool_results: list[dict[str, Any]] = field(default_factory=list)


class Engine:
    """Turn-level model/tool loop."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def ask(self, user_message: str, *, on_text: TextSink | None = None) -> AgentRunResult:
        final_result: AgentRunResult | None = None
        for event in self.run_turn(user_message, on_text=on_text):
            if event["type"] in {"final", "stop"}:
                final_result = event["result"]
        if final_result is None:
            return AgentRunResult(
                final_text="",
                messages=self.runtime.messages,
                steps=0,
                hit_step_limit=False,
                stop_reason="unknown",
            )
        return final_result

    def run_turn(
        self,
        user_message: str,
        *,
        on_text: TextSink | None = None,
    ) -> Iterator[dict[str, Any]]:
        runtime = self.runtime
        turn_started_at = time.monotonic()
        task_state = runtime.start_task(user_message)
        runtime.run_hooks("before_turn", {"user_message": user_message})
        yield {
            "type": "turn_started",
            "run_id": task_state.run_id,
            "turn_id": task_state.turn_id,
        }
        runtime.messages.append(build_user_message(user_message))
        usage: ProviderUsage | None = None
        final_text = ""
        tool_results: list[dict[str, Any]] = []

        for step in range(1, runtime.config.max_steps + 1):
            task_state.record_attempt()
            runtime.run_store.write_task_state(task_state)
            runtime.emit_event(
                "model_requested",
                {"step": step, "message_count": len(runtime.messages)},
            )
            runtime.run_hooks("before_model", {"step": step})
            yield {
                "type": "model_requested",
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "step": step,
            }
            model_started_at = time.monotonic()
            completion = runtime.provider.complete(
                runtime.messages,
                runtime.tool_schemas(),
                stream=runtime.config.stream,
                on_text=on_text,
            )
            model_duration_ms = int((time.monotonic() - model_started_at) * 1000)
            usage = completion.usage or usage
            final_text = completion.text
            runtime.emit_event(
                "model_completed",
                {
                    "step": step,
                    "stop_reason": completion.stop_reason,
                    "duration_ms": model_duration_ms,
                    "raw_stop_reason": completion.raw_stop_reason,
                    "output_chars": len(completion.text),
                    "tool_call_count": len(completion.tool_calls),
                },
            )
            runtime.run_hooks(
                "after_model",
                {
                    "step": step,
                    "stop_reason": completion.stop_reason,
                    "tool_call_count": len(completion.tool_calls),
                },
            )
            yield {
                "type": "model_completed",
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "step": step,
                "stop_reason": completion.stop_reason,
                "raw_stop_reason": completion.raw_stop_reason,
                "duration_ms": model_duration_ms,
            }

            if completion.stop_reason == "tool_calls":
                yield from self._execute_tool_calls(step, completion, tool_results, task_state)
                continue

            if completion.stop_reason in {"stop", "unknown"}:
                runtime.run_hooks("before_final", {"step": step, "stop_reason": completion.stop_reason})
                result = self._finish(step, completion, usage, tool_results, task_state)
                self._record_turn_finished(task_state, result, turn_started_at)
                yield {
                    "type": "final",
                    "run_id": task_state.run_id,
                    "turn_id": task_state.turn_id,
                    "content": completion.text,
                    "result": result,
                }
                runtime.finish_task()
                return

            result = self._stop(step, completion, usage, tool_results, task_state)
            self._record_turn_finished(task_state, result, turn_started_at)
            yield {
                "type": "stop",
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "content": completion.text,
                "result": result,
            }
            runtime.finish_task()
            return

        task_state.finish(status="stopped", stop_reason="step_limit", final_text=final_text)
        result = AgentRunResult(
            final_text=final_text,
            messages=runtime.messages,
            steps=runtime.config.max_steps,
            usage=usage,
            hit_step_limit=True,
            stop_reason="step_limit",
            run_id=task_state.run_id,
            turn_id=task_state.turn_id,
            tool_results=tool_results,
        )
        self._record_turn_finished(task_state, result, turn_started_at)
        yield {
            "type": "stop",
            "run_id": task_state.run_id,
            "turn_id": task_state.turn_id,
            "content": final_text,
            "result": result,
        }
        runtime.finish_task()

    def _execute_tool_calls(
        self,
        step: int,
        completion: ChatCompletionResult,
        tool_results: list[dict[str, Any]],
        task_state: TaskState,
    ) -> Iterator[dict[str, Any]]:
        runtime = self.runtime
        runtime.messages.append(assistant_message(completion.text, completion.tool_calls))
        for tool_call in completion.tool_calls:
            task_state.record_tool(tool_call.name)
            runtime.run_store.write_task_state(task_state)
            runtime.emit_event(
                "tool_started",
                {
                    "step": step,
                    "tool_name": tool_call.name,
                    "args": tool_call.arguments,
                },
            )
            yield {
                "type": "tool_started",
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "step": step,
                "tool_call": tool_call,
            }
            tool_started_at = time.monotonic()
            tool_result = runtime.run_tool(tool_call)
            duration_ms = int((time.monotonic() - tool_started_at) * 1000)
            tool_results.append(tool_result)
            runtime.messages.append(tool_message(tool_call.id, tool_result["content"]))
            runtime.emit_event(
                "tool_finished",
                {
                    "step": step,
                    "tool_name": tool_call.name,
                    "is_error": tool_result["is_error"],
                    "duration_ms": duration_ms,
                    "output_chars": len(tool_result["content"]),
                    "metadata": tool_result.get("metadata", {}),
                },
            )
            yield {
                "type": "tool_result",
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "step": step,
                "tool_call": tool_call,
                "result": tool_result,
                "duration_ms": duration_ms,
            }

    def _finish(
        self,
        step: int,
        completion: ChatCompletionResult,
        usage: ProviderUsage | None,
        tool_results: list[dict[str, Any]],
        task_state: TaskState,
    ) -> AgentRunResult:
        self.runtime.messages.append(assistant_message(completion.text))
        task_state.finish(
            status="completed",
            stop_reason=completion.stop_reason,
            final_text=completion.text,
        )
        return AgentRunResult(
            final_text=completion.text,
            messages=self.runtime.messages,
            steps=step,
            usage=usage,
            stop_reason=completion.stop_reason,
            run_id=task_state.run_id,
            turn_id=task_state.turn_id,
            tool_results=tool_results,
        )

    def _stop(
        self,
        step: int,
        completion: ChatCompletionResult,
        usage: ProviderUsage | None,
        tool_results: list[dict[str, Any]],
        task_state: TaskState,
    ) -> AgentRunResult:
        self.runtime.messages.append(assistant_message(completion.text))
        task_state.finish(
            status="stopped",
            stop_reason=completion.stop_reason,
            final_text=completion.text,
        )
        return AgentRunResult(
            final_text=completion.text,
            messages=self.runtime.messages,
            steps=step,
            usage=usage,
            hit_step_limit=completion.stop_reason == "length",
            stop_reason=completion.stop_reason,
            run_id=task_state.run_id,
            turn_id=task_state.turn_id,
            tool_results=tool_results,
        )

    def _record_turn_finished(
        self,
        task_state: TaskState,
        result: AgentRunResult,
        turn_started_at: float,
    ) -> None:
        runtime = self.runtime
        duration_ms = int((time.monotonic() - turn_started_at) * 1000)
        runtime.emit_event(
            "assistant_message",
            {
                "content": _clip(result.final_text, 500),
                "stop_reason": result.stop_reason,
            },
        )
        runtime.emit_event(
            "turn_finished",
            {
                "status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "duration_ms": duration_ms,
            },
        )
        runtime.emit_event(
            "run_finished",
            {
                "run_status": task_state.status,
                "stop_reason": task_state.stop_reason,
                "duration_ms": duration_ms,
                "output_chars": len(result.final_text),
            },
        )
        runtime.write_report(task_state, usage=result.usage, tool_results=result.tool_results)


def _clip(value: str, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
