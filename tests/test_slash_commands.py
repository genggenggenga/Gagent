from pathlib import Path

from gagent.commands.slash import command_help_text, resolve_command, suggest_commands
from gagent.cli import handle_repl_command
from gagent.core.runtime import AgentConfig, GagentRuntime
from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolSchema


class NoCallProvider:
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
        return ChatCompletionResult(text="should not be called", stop_reason="stop")


def build_runtime(tmp_path: Path, *, tool_profile: str = "default") -> GagentRuntime:
    return GagentRuntime(
        provider=NoCallProvider(),
        config=AgentConfig(
            cwd=tmp_path,
            model="fake-model",
            stream=False,
            tool_profile=tool_profile,
        ),
    )


def test_slash_registry_resolves_aliases_and_suggestions():
    assert resolve_command("quit").name == "exit"
    assert resolve_command("/h").name == "help"
    assert [command.name for command in suggest_commands("/st")] == ["status"]

    help_text = command_help_text()

    assert "/status" in help_text
    assert "/tools" in help_text
    assert "/clear" in help_text


def test_status_command_reports_runtime_state(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    handled, should_exit, output = handle_repl_command(runtime, "/status")

    assert handled is True
    assert should_exit is False
    assert f"session id: {runtime.session_id}" in output
    assert "model: fake-model" in output
    assert "tool profile: default" in output
    assert "messages: 1" in output


def test_tools_command_uses_current_tool_profile(tmp_path: Path):
    runtime = build_runtime(tmp_path, tool_profile="readonly")

    handled, should_exit, output = handle_repl_command(runtime, "/tools")

    assert handled is True
    assert should_exit is False
    assert "read_file\tread\t" in output
    assert "todo_write\tread\t" in output
    assert "bash\t" not in output
    assert "edit_file\t" not in output


def test_clear_command_creates_empty_session_and_resets_runtime_state(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    old_session_id = runtime.session_id
    runtime.messages.append({"role": "user", "content": "old message"})
    runtime.session.todos = [{"content": "old todo", "status": "in_progress"}]
    runtime.session.run_ids.append("run_old")
    runtime.current_run_id = "run_old"
    runtime.tool_policy_checker.fresh_reads.add(tmp_path / "README.md")

    handled, should_exit, output = handle_repl_command(runtime, "/clear")

    assert handled is True
    assert should_exit is False
    assert output.startswith("new session session_")
    assert runtime.session_id != old_session_id
    assert [message["role"] for message in runtime.messages] == ["system"]
    assert runtime.session.todos == []
    assert runtime.session.run_ids == []
    assert runtime.current_run_id == ""
    assert runtime.tool_policy_checker.fresh_reads == set()
    assert runtime.session_store.path(old_session_id).exists()
    assert runtime.session_store.path(runtime.session_id).exists()


def test_exit_and_unknown_commands_do_not_call_provider(tmp_path: Path):
    provider = NoCallProvider()
    runtime = GagentRuntime(
        provider=provider,
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    handled, should_exit, output = handle_repl_command(runtime, "/quit")
    assert handled is True
    assert should_exit is True
    assert output == ""

    handled, should_exit, output = handle_repl_command(runtime, "/missing")
    assert handled is True
    assert should_exit is False
    assert output == "Unknown command: /missing. Use /help."
    assert provider.calls == 0
