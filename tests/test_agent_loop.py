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
        "model_requested",
        "model_completed",
        "tool_started",
        "tool_finished",
        "model_requested",
        "model_completed",
        "assistant_message",
        "turn_finished",
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
