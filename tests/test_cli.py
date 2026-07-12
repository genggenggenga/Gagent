from pathlib import Path

from gagent.cli import build_arg_parser, run_agent_turn, welcome_banner
from gagent.core.runtime import AgentConfig, GagentRuntime
from gagent.providers.types import ChatCompletionResult, Message, TextSink, ToolCall, ToolSchema


def test_cli_parser_accepts_first_stage_runtime_options():
    parser = build_arg_parser()

    args = parser.parse_args(
        [
            "--cwd",
            ".",
            "--model",
            "openai/gpt-4o-mini",
            "--tool-profile",
            "readonly",
            "--max-steps",
            "3",
            "hello",
        ]
    )

    assert args.cwd == "."
    assert args.model == "openai/gpt-4o-mini"
    assert args.tool_profile == "readonly"
    assert args.max_steps == 3
    assert args.prompt == ["hello"]


def test_welcome_banner_contains_project_name():
    banner = welcome_banner(color=False)

    assert "Gagent" in banner
    assert "/\\_/\\" in banner


class CliFakeProvider:
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
        del messages, tools, stream
        self.calls += 1
        if self.calls == 1:
            return ChatCompletionResult(
                stop_reason="tool_calls",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "README.md"},
                    ),
                ),
            )
        if on_text:
            on_text("done")
        return ChatCompletionResult(text="done", stop_reason="stop")


def test_cli_prints_tool_prefix(capsys, tmp_path: Path):
    (tmp_path / "README.md").write_text("# Gagent\n", encoding="utf-8")
    runtime = GagentRuntime(
        provider=CliFakeProvider(),
        config=AgentConfig(cwd=tmp_path, model="fake-model", stream=False),
    )

    result = run_agent_turn(runtime, "read README")

    output = capsys.readouterr().out
    assert result.final_text == "done"
    assert "[tool] read_file" in output
    assert "[tool] read_file finished (ok" in output
