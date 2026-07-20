import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gagent import __version__
from gagent.commands.slash import command_help_text, resolve_command
from gagent.config import resolve_runtime_config
from gagent.core.engine import AgentRunResult
from gagent.core.runtime import GagentRuntime
from gagent.core.session_store import SessionStore
from gagent.providers import LiteLLMProvider
from gagent.tools.registry import build_tool_profiles


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gagent - a Python coding agent built harness by harness.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument("--model", default=None, help="LiteLLM model name.")
    parser.add_argument("--api-base", default=None, help="Custom provider API base URL.")
    parser.add_argument("--api-key", default=None, help="Provider API key override.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature.")
    parser.add_argument("--timeout", type=int, default=300, help="Provider timeout in seconds.")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum model/tool loop steps.")
    parser.add_argument(
        "--tool-profile",
        choices=("default", "readonly", "no_shell"),
        default="default",
        help="Tool capability profile exposed to the model.",
    )
    parser.add_argument(
        "--approval-policy",
        choices=("auto", "never"),
        default="auto",
        help="Permission policy for mutating or executing tools.",
    )
    parser.add_argument(
        "--sandbox",
        choices=("off", "best_effort", "required"),
        default="off",
        help="Shell sandbox mode for bash tool execution.",
    )
    parser.add_argument(
        "--sandbox-backend",
        choices=("auto", "bubblewrap", "none"),
        default="auto",
        help="Sandbox backend for shell execution.",
    )
    parser.add_argument("--list-tools", action="store_true", help="List enabled tools and exit.")
    parser.add_argument(
        "--resume",
        default=None,
        metavar="SESSION",
        help="Resume a previous session by id, or use 'latest'.",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List persisted sessions and exit.",
    )
    parser.add_argument("--no-stream", action="store_true", help="Disable provider streaming.")
    return parser


def build_runtime(args: argparse.Namespace) -> GagentRuntime:
    config = resolve_runtime_config(args)
    provider = LiteLLMProvider(
        model=config.model,
        api_base=config.api_base,
        api_key=config.api_key,
        temperature=config.temperature,
        timeout=config.timeout,
    )
    return GagentRuntime(
        provider=provider,
        config=config,
        session_id=None if args.resume in {None, "latest"} else args.resume,
        resume_latest=args.resume == "latest",
    )


def run_agent_turn(agent: GagentRuntime, prompt: str) -> AgentRunResult:
    """Run one prompt and print model/tool progress for the terminal UI."""

    final_result: AgentRunResult | None = None
    text_chunks: list[str] = []

    def on_text(text: str) -> None:
        text_chunks.append(text)
        print(text, end="", flush=True)

    for event in agent.engine.run_turn(prompt, on_text=on_text):
        event_type = event["type"]
        if event_type == "tool_started":
            _print_tool_started(event, text_chunks)
        elif event_type == "tool_result":
            _print_tool_finished(event)
        elif event_type in {"final", "stop"}:
            final_result = event["result"]

    if final_result is None:
        return AgentRunResult(
            final_text="",
            messages=agent.messages,
            steps=0,
            hit_step_limit=False,
            stop_reason="unknown",
        )
    if final_result.final_text:
        if not text_chunks:
            print(final_result.final_text)
        else:
            print()
    return final_result


def _print_tool_started(event: dict[str, Any], text_chunks: list[str]) -> None:
    tool_call = event["tool_call"]
    if text_chunks and not "".join(text_chunks).endswith("\n"):
        print()
    args = json.dumps(tool_call.arguments, ensure_ascii=False, sort_keys=True)
    print(f"{_tool_prefix()} {tool_call.name} {args}")


def _print_tool_finished(event: dict[str, Any]) -> None:
    result = event["result"]
    status = "error" if result["is_error"] else "ok"
    duration_ms = int(event.get("duration_ms", 0) or 0)
    print(f"{_tool_prefix()} {result['name']} finished ({status}, {duration_ms}ms)")


def _tool_prefix() -> str:
    label = "[tool]"
    if sys.stdout.isatty():
        return f"\033[35m{label}\033[0m"
    return label


def print_sessions(cwd: str) -> None:
    store = SessionStore(Path(cwd).expanduser().resolve() / ".gagent" / "sessions")
    rows = store.list_sessions()
    if not rows:
        print("No sessions found.")
        return
    for row in rows:
        print(
            "\t".join(
                [
                    row["id"],
                    row["updated_at"],
                    f"messages={row['message_count']}",
                    f"runs={row['run_count']}",
                    row["last_user_message"],
                ]
            )
        )


def handle_repl_command(agent: GagentRuntime, user_input: str) -> tuple[bool, bool, str]:
    """Handle slash commands before a prompt reaches the model."""

    text = str(user_input or "").strip()
    if not text.startswith("/"):
        return False, False, ""

    raw_command, _, command_args = text[1:].partition(" ")
    resolved = resolve_command(raw_command)
    if resolved is None:
        return True, False, f"Unknown command: /{raw_command}. Use /help."

    command_name = resolved.name
    if command_name == "exit":
        return True, True, ""
    if command_name == "help":
        return True, False, command_help_text()
    if command_name == "status":
        return True, False, format_status(agent)
    if command_name == "tools":
        return True, False, format_tools(agent)
    if command_name == "clear":
        if command_args.strip():
            return True, False, "Usage: /clear"
        session_id = agent.clear_session()
        return True, False, f"new session {session_id}"
    return True, False, f"Unknown command: /{raw_command}. Use /help."


def format_status(agent: GagentRuntime) -> str:
    last_run_id = agent.session.run_ids[-1] if agent.session.run_ids else ""
    last_run_dir = str(agent.run_store.root / last_run_id) if last_run_id else "-"
    todo_counts = _todo_counts(agent.session.todos)
    return "\n".join(
        [
            f"session id: {agent.session_id}",
            f"session path: {agent.session_store.path(agent.session_id)}",
            f"events path: {agent.session_event_bus.path}",
            f"cwd: {agent.workspace.cwd}",
            f"repo root: {agent.workspace.repo_root}",
            f"model: {agent.config.model}",
            f"tool profile: {agent.tool_profile.name}",
            f"messages: {len(agent.messages)}",
            (
                "todos: "
                f"pending={todo_counts['pending']} "
                f"in_progress={todo_counts['in_progress']} "
                f"completed={todo_counts['completed']}"
            ),
            f"last run id: {last_run_id or '-'}",
            f"last run dir: {last_run_dir}",
        ]
    )


def format_tools(agent: GagentRuntime) -> str:
    lines = []
    for tool in agent.tools.tools_for_profile(agent.tool_profile):
        marker = "read" if tool.read_only else tool.risk_level
        lines.append(f"{tool.name}\t{marker}\t{tool.description}")
    return "\n".join(lines)


def _todo_counts(todos: list[dict[str, str]]) -> dict[str, int]:
    counts = {"pending": 0, "in_progress": 0, "completed": 0}
    for todo in todos:
        status = str(todo.get("status", ""))
        if status in counts:
            counts[status] += 1
    return counts


def welcome_banner(*, color: bool | None = None) -> str:
    """Return the interactive welcome banner."""

    use_color = sys.stdout.isatty() if color is None else color
    banner = r"""
   /\_/\
  ( o.o )   Gagent
   > ^ <    tiny paws, sharp tools
"""
    if not use_color:
        return banner.strip("\n")
    return f"\033[36m{banner.strip('\n')}\033[0m"


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_sessions:
        print_sessions(args.cwd)
        return 0

    agent = build_runtime(args)

    if args.list_tools:
        profiles = build_tool_profiles(agent.tools)
        profile = profiles[args.tool_profile]
        for tool in agent.tools.tools_for_profile(profile):
            marker = "read" if tool.read_only else tool.risk_level
            print(f"{tool.name}\t{marker}\t{tool.description}")
        return 0

    prompt = " ".join(args.prompt).strip()
    if prompt:
        handled, should_exit, output = handle_repl_command(agent, prompt)
        if should_exit:
            return 0
        if handled:
            if output:
                print(output)
            return 0
        result = run_agent_turn(agent, prompt)
        if result.hit_step_limit:
            print(f"gagent: hit max steps ({result.steps})", file=sys.stderr)
            return 2
        return 0

    if not sys.stdin.isatty():
        parser.print_help()
        return 0

    print(welcome_banner())
    print(f"gagent {__version__}")
    print(f"model: {agent.config.model} | cwd: {agent.config.cwd}")
    print("输入问题后回车发送；输入 /help 查看命令；输入 /exit 或 /quit 退出。\n")
    while True:
        try:
            user_input = input("gagent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_input:
            continue
        handled, should_exit, output = handle_repl_command(agent, user_input)
        if should_exit:
            return 0
        if handled:
            if output:
                print(output)
            continue
        result = run_agent_turn(agent, user_input)
        if result.hit_step_limit:
            print(f"gagent: hit max steps ({result.steps})", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
