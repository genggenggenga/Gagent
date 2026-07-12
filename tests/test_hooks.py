from pathlib import Path
import json

from gagent.core.hooks import HookContext, HookResult
from gagent.core.runtime import AgentConfig, GagentRuntime
from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolCall, ToolSchema


class StaticProvider:
    model = "fake-model"

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        del messages, tools, stream, on_text
        return ChatCompletionResult(text="done", stop_reason="stop")


def test_hook_manager_runs_hooks_in_registration_order(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )
    seen = []

    def first(context: HookContext):
        seen.append(("first", context.point))
        return HookResult.allow()

    def second(context: HookContext):
        seen.append(("second", context.point))
        return HookResult.allow()

    runtime.hooks.register("before_model", first, name="first")
    runtime.hooks.register("before_model", second, name="second")

    result = runtime.run_hooks("before_model", {"step": 1})

    assert result.allowed
    assert seen == [("first", "before_model"), ("second", "before_model")]


def test_before_tool_hook_can_deny_tool_execution(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    def deny_write(context: HookContext):
        if context.payload["tool"].name == "write_file":
            return HookResult.deny(
                "test_denied",
                message="error: denied by test hook",
                metadata={"tool_error_code": "test_denied"},
            )
        return HookResult.allow()

    runtime.hooks.register("before_tool", deny_write, name="deny_write")

    result = runtime.run_tool(
        ToolCall(
            id="call_1",
            name="write_file",
            arguments={"path": "notes.txt", "content": "hello\n"},
        )
    )

    assert result["is_error"]
    assert result["content"] == "error: denied by test hook"
    assert result["metadata"]["tool_error_code"] == "test_denied"
    assert not (tmp_path / "notes.txt").exists()


def test_runtime_consumers_derive_changed_paths_and_tool_stats(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )
    task_state = runtime.start_task("write a file")

    result = runtime.run_tool(
        ToolCall(
            id="call_1",
            name="write_file",
            arguments={"path": "notes.txt", "content": "hello\n"},
        )
    )
    runtime.emit_event(
        "tool_finished",
        {
            "tool_name": "write_file",
            "is_error": result["is_error"],
            "duration_ms": 3,
            "metadata": result["metadata"],
        },
    )

    assert task_state.changed_paths == ["notes.txt"]
    assert task_state.tool_stats["write_file"] == {
        "calls": 1,
        "errors": 0,
        "duration_ms": 3,
    }


def test_denied_decision_becomes_runtime_reminder(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )
    task_state = runtime.start_task("try shell search")

    runtime.run_tool(
        ToolCall(id="call_1", name="bash", arguments={"command": "grep -R hello ."})
    )

    assert task_state.runtime_reminders
    assert task_state.runtime_reminders[0]["reason"] == "shell_search_should_use_tool"

    trace = [
        json.loads(line)
        for line in (runtime.current_run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "tool_policy_decision" for event in trace)
