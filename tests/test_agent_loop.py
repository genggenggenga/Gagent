from pathlib import Path
import json

from gagent.core.runtime import AgentConfig, GagentRuntime
from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolCall, ToolSchema


class FakeProvider:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        assert stream is False
        self.calls += 1
        if self.calls == 1:
            assert tools
            return ChatCompletionResult(
                stop_reason="tool_calls",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "README.md", "start": 1, "end": 1},
                    ),
                ),
            )

        assert messages[-1]["role"] == "tool"
        assert "Gagent" in messages[-1]["content"]
        if on_text:
            on_text("README checked.")
        return ChatCompletionResult(text="README checked.", stop_reason="stop")


class LengthStopProvider:
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
        return ChatCompletionResult(
            text="partial answer",
            stop_reason="length",
            raw_stop_reason="length",
        )


class TodoProvider:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        del stream, on_text
        self.calls += 1
        if self.calls == 1:
            assert tools
            assert any(tool["function"]["name"] == "todo_write" for tool in tools)
            return ChatCompletionResult(
                stop_reason="tool_calls",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="todo_write",
                        arguments={
                            "todos": [
                                {"content": "Inspect design", "status": "completed"},
                                {"content": "Implement todo state", "status": "in_progress"},
                            ]
                        },
                    ),
                ),
            )

        assert messages[-1]["role"] == "tool"
        assert "Current todos:" in messages[-1]["content"]
        return ChatCompletionResult(text="Todos tracked.", stop_reason="stop")


def test_agent_loop_executes_tool_calls(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Gagent\n", encoding="utf-8")
    provider = FakeProvider()
    runtime = GagentRuntime(
        provider=provider,
        config=AgentConfig(cwd=tmp_path, model=provider.model, stream=False),
    )

    result = runtime.ask("read the README")

    assert result.final_text == "README checked."
    assert provider.calls == 2
    assert result.tool_results[0]["name"] == "read_file"
    assert not result.hit_step_limit


def test_runtime_builds_workspace_aware_system_prompt(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Rules\nUse tiny edits.\n", encoding="utf-8")
    runtime = GagentRuntime(
        provider=LengthStopProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    assert runtime.workspace.repo_root == tmp_path.resolve()
    assert runtime.messages[0]["role"] == "system"
    assert "## Workspace" in runtime.messages[0]["content"]
    assert "### AGENTS.md" in runtime.messages[0]["content"]
    assert runtime.system_prompt.workspace_fingerprint == runtime.workspace.fingerprint()


def test_engine_emits_turn_events(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Gagent\n", encoding="utf-8")
    runtime = GagentRuntime(
        provider=FakeProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    events = list(runtime.engine.run_turn("read the README"))

    assert events[0]["type"] == "turn_started"
    assert events[1]["type"] == "model_requested"
    assert events[2]["type"] == "model_completed"
    assert events[2]["stop_reason"] == "tool_calls"
    assert any(event["type"] == "tool_started" for event in events)
    assert any(event["type"] == "tool_result" for event in events)
    assert events[-1]["type"] == "final"


def test_engine_persists_session_events_and_run_artifacts(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Gagent\n", encoding="utf-8")
    runtime = GagentRuntime(
        provider=FakeProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    result = runtime.ask("read the README")
    run_dir = tmp_path / ".gagent" / "runs" / result.run_id

    assert run_dir.exists()
    assert (run_dir / "task_state.json").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "report.json").exists()

    session_events = [
        json.loads(line)
        for line in runtime.session_event_bus.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event"] for event in session_events] == [
        "session_started",
        "turn_started",
        "user_message",
        "run_started",
        "model_requested",
        "model_completed",
        "tool_started",
        "tool_policy_decision",
        "permission_decision",
        "tool_finished",
        "model_requested",
        "model_completed",
        "assistant_message",
        "turn_finished",
        "run_finished",
    ]

    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["event"] == "tool_finished" for event in trace_events)
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["run_id"] == result.run_id
    assert report["turn_id"] == result.turn_id
    assert report["tool_results"][0]["name"] == "read_file"


def test_engine_stops_on_length_finish_reason(tmp_path: Path):
    runtime = GagentRuntime(
        provider=LengthStopProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    result = runtime.ask("write a long answer")

    assert result.final_text == "partial answer"
    assert result.hit_step_limit
    assert result.stop_reason == "length"


def test_todo_write_updates_task_state_and_report(tmp_path: Path):
    provider = TodoProvider()
    runtime = GagentRuntime(
        provider=provider,
        config=AgentConfig(cwd=tmp_path, model=provider.model, stream=False),
    )

    result = runtime.ask("track a multi-step task")
    run_dir = tmp_path / ".gagent" / "runs" / result.run_id

    task_state = json.loads((run_dir / "task_state.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result.final_text == "Todos tracked."
    assert task_state["todos"] == [
        {"content": "Inspect design", "status": "completed"},
        {"content": "Implement todo state", "status": "in_progress"},
    ]
    assert report["todos"] == task_state["todos"]
    assert task_state["todo_changes"][0]["counts"] == {
        "completed": 1,
        "in_progress": 1,
        "pending": 0,
    }
    assert any(
        event["event"] == "tool_finished" and event["tool_name"] == "todo_write"
        for event in trace_events
    )
