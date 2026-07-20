from pathlib import Path
import json

from gagent.core.runtime import AgentConfig, GagentRuntime
from gagent.core.session_store import SessionStore
from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolCall, ToolSchema


class EchoProvider:
    model = "fake-model"

    def __init__(self, text: str = "done") -> None:
        self.text = text
        self.seen_messages: list[list[Message]] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        *,
        stream: bool = True,
        on_text: TextSink | None = None,
    ) -> ChatCompletionResult:
        del tools, stream, on_text
        self.seen_messages.append([dict(message) for message in messages])
        return ChatCompletionResult(text=self.text, stop_reason="stop")


class TodoSessionProvider:
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
        del messages, tools, stream, on_text
        self.calls += 1
        if self.calls == 1:
            return ChatCompletionResult(
                stop_reason="tool_calls",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="todo_write",
                        arguments={
                            "todos": [
                                {"content": "Persist todo state", "status": "in_progress"}
                            ]
                        },
                    ),
                ),
            )
        return ChatCompletionResult(text="tracked", stop_reason="stop")


def test_runtime_creates_and_updates_session_json(tmp_path: Path):
    provider = EchoProvider("first answer")
    runtime = GagentRuntime(
        provider=provider,
        config=AgentConfig(cwd=tmp_path, model=provider.model, stream=False),
    )

    session_path = tmp_path / ".gagent" / "sessions" / f"{runtime.session_id}.json"
    assert session_path.exists()

    result = runtime.ask("first question")
    session = json.loads(session_path.read_text(encoding="utf-8"))

    assert session["id"] == runtime.session_id
    assert session["schema_version"] == 1
    assert session["run_ids"] == [result.run_id]
    assert [message["role"] for message in session["messages"]] == [
        "system",
        "user",
        "assistant",
    ]
    assert session["messages"][-1]["content"] == "first answer"


def test_runtime_resumes_session_by_id(tmp_path: Path):
    first_provider = EchoProvider("first answer")
    first_runtime = GagentRuntime(
        provider=first_provider,
        config=AgentConfig(cwd=tmp_path, model=first_provider.model, stream=False),
    )
    first_runtime.ask("first question")

    second_provider = EchoProvider("second answer")
    second_runtime = GagentRuntime(
        provider=second_provider,
        config=AgentConfig(cwd=tmp_path, model=second_provider.model, stream=False),
        session_id=first_runtime.session_id,
    )
    second_runtime.ask("second question")

    seen = second_provider.seen_messages[0]
    assert second_runtime.session_id == first_runtime.session_id
    assert any(message.get("content") == "first question" for message in seen)
    assert any(message.get("content") == "first answer" for message in seen)
    assert seen[-1]["content"] == "second question"


def test_runtime_resumes_latest_session(tmp_path: Path):
    first_runtime = GagentRuntime(
        provider=EchoProvider("first"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )
    second_runtime = GagentRuntime(
        provider=EchoProvider("second"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    resumed = GagentRuntime(
        provider=EchoProvider("resumed"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
        resume_latest=True,
    )

    assert first_runtime.session_id != second_runtime.session_id
    assert resumed.session_id == second_runtime.session_id


def test_resume_refreshes_changed_system_prompt(tmp_path: Path):
    runtime = GagentRuntime(
        provider=EchoProvider("answer"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )
    old_system = runtime.messages[0]["content"]

    (tmp_path / "AGENTS.md").write_text("# Rules\nNew rule.\n", encoding="utf-8")
    resumed = GagentRuntime(
        provider=EchoProvider("answer"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
        session_id=runtime.session_id,
    )

    assert resumed.messages[0]["role"] == "system"
    assert resumed.messages[0]["content"] != old_system
    assert resumed.resume_warnings == ["system prompt changed; refreshed the system message"]


def test_todos_are_persisted_in_session(tmp_path: Path):
    runtime = GagentRuntime(
        provider=TodoSessionProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    runtime.ask("track todos")
    session = SessionStore(tmp_path / ".gagent" / "sessions").load(runtime.session_id)
    resumed = GagentRuntime(
        provider=EchoProvider("next"),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
        session_id=runtime.session_id,
    )

    assert session.todos == [{"content": "Persist todo state", "status": "in_progress"}]
    assert resumed.session.todos == session.todos
