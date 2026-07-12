from pathlib import Path
import json

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


def test_permission_denies_bash_when_profile_disallows_shell(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(
            cwd=tmp_path,
            model="fake-model",
            tool_profile="no_shell",
            stream=False,
        ),
    )

    result = runtime.run_tool(
        ToolCall(id="call_1", name="bash", arguments={"command": "echo hi"})
    )

    assert result["is_error"]
    assert result["metadata"]["tool_error_code"] == "tool_not_allowed"


def test_permission_never_denies_mutating_and_execute_tools(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(
            cwd=tmp_path,
            model="fake-model",
            approval_policy="never",
            stream=False,
        ),
    )

    write_result = runtime.run_tool(
        ToolCall(
            id="call_1",
            name="write_file",
            arguments={"path": "new.txt", "content": "hello\n"},
        )
    )
    bash_result = runtime.run_tool(
        ToolCall(id="call_2", name="bash", arguments={"command": "echo hi"})
    )

    assert write_result["is_error"]
    assert write_result["metadata"]["tool_error_code"] == "approval_denied"
    assert bash_result["is_error"]
    assert bash_result["metadata"]["tool_error_code"] == "approval_denied"
    assert not (tmp_path / "new.txt").exists()


def test_tool_policy_requires_read_before_editing_existing_file(tmp_path: Path):
    target = tmp_path / "README.md"
    target.write_text("hello world\n", encoding="utf-8")
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    rejected = runtime.run_tool(
        ToolCall(
            id="call_1",
            name="edit_file",
            arguments={"path": "README.md", "old_text": "world", "new_text": "Gagent"},
        )
    )
    read = runtime.run_tool(
        ToolCall(id="call_2", name="read_file", arguments={"path": "README.md"})
    )
    edited = runtime.run_tool(
        ToolCall(
            id="call_3",
            name="edit_file",
            arguments={"path": "README.md", "old_text": "world", "new_text": "Gagent"},
        )
    )

    assert rejected["is_error"]
    assert rejected["metadata"]["tool_error_code"] == "prior_read_required"
    assert not read["is_error"]
    assert not edited["is_error"]
    assert target.read_text(encoding="utf-8") == "hello Gagent\n"


def test_tool_policy_rejects_shell_search_commands(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    result = runtime.run_tool(
        ToolCall(id="call_1", name="bash", arguments={"command": "grep -R hello ."})
    )

    assert result["is_error"]
    assert result["metadata"]["tool_error_code"] == "shell_search_should_use_tool"
    assert "use grep" in result["content"]


def test_permission_and_policy_decisions_are_persisted(tmp_path: Path):
    runtime = GagentRuntime(
        provider=StaticProvider(),
        config=AgentConfig(
            cwd=tmp_path,
            model="fake-model",
            approval_policy="never",
            stream=False,
        ),
    )

    runtime.run_tool(ToolCall(id="call_1", name="bash", arguments={"command": "echo hi"}))

    events = [
        json.loads(line)
        for line in runtime.session_event_bus.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert any(event["event"] == "tool_policy_decision" for event in events)
    assert any(
        event["event"] == "permission_decision"
        and event["decision"] == "deny"
        and event["reason"] == "approval_denied"
        for event in events
    )
