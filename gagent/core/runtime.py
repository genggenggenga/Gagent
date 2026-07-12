"""Runtime state and dependency composition for Gagent."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from gagent.core.engine import AgentRunResult, Engine, TextSink
from gagent.core.messages import system_message
from gagent.core.prompt import build_system_prompt
from gagent.core.run_store import RunStore
from gagent.core.runtime_events import build_runtime_event
from gagent.core.session_events import SessionEventBus
from gagent.core.task_state import TaskState
from gagent.core.workspace import WorkspaceContext
from gagent.providers.base import Provider
from gagent.providers.types import ToolCall
from gagent.tools.base import ToolExecutionContext
from gagent.tools.registry import (
    ToolRegistry,
    build_builtin_registry,
    resolve_tool_profile,
)


@dataclass(frozen=True)
class AgentConfig:
    """Configuration needed by the first-stage agent runtime."""

    cwd: Path
    model: str
    api_base: str | None = None
    api_key: str | None = None
    temperature: float = 0.2
    timeout: int = 300
    max_steps: int = 20
    stream: bool = True
    tool_profile: str = "default"


class GagentRuntime:
    """Runtime object that owns state and delegates turn execution to Engine."""

    def __init__(
        self,
        *,
        provider: Provider,
        config: AgentConfig,
        tools: ToolRegistry | None = None,
        messages: list[dict] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.tools = tools or build_builtin_registry()
        self.tool_profile = resolve_tool_profile(self.tools, config.tool_profile)
        self.workspace = WorkspaceContext.build(config.cwd)
        self.tool_context = ToolExecutionContext(cwd=config.cwd, workspace=self.workspace)
        self.system_prompt = build_system_prompt(
            workspace=self.workspace,
            tools=self.tools,
            profile=self.tool_profile,
        )
        self.messages = messages or [system_message(self.system_prompt.text)]
        self.session_id = _new_session_id()
        self.session_dir = config.cwd / ".gagent" / "sessions"
        self.run_store = RunStore(config.cwd / ".gagent" / "runs")
        self.session_event_bus = SessionEventBus(
            session_id=self.session_id,
            path=self.session_dir / f"{self.session_id}.events.jsonl",
        )
        self.current_task_state: TaskState | None = None
        self.current_run_dir: Path | None = None
        self.current_turn_id = ""
        self.current_run_id = ""
        self._trace_seq = 0
        self.session_event_bus.emit(
            "session_started",
            {
                "workspace_root": str(self.workspace.repo_root),
                "cwd": str(self.workspace.cwd),
                "model": config.model,
                "system_prompt_hash": self.system_prompt.hash,
            },
        )
        self.engine = Engine(self)

    def ask(self, user_message: str, *, on_text: TextSink | None = None) -> AgentRunResult:
        return self.engine.ask(user_message, on_text=on_text)

    def tool_schemas(self) -> list[dict]:
        return self.tools.schemas_for_profile(self.tool_profile)

    def run_tool(self, tool_call: ToolCall) -> dict:
        result = self.tools.execute(
            tool_call.name,
            tool_call.arguments,
            self.tool_context,
            self.tool_profile,
        )
        return {
            "id": tool_call.id,
            "name": tool_call.name,
            "is_error": result.is_error,
            "content": result.content,
            "metadata": result.metadata or {},
        }

    def start_task(self, user_message: str) -> TaskState:
        task_state = TaskState.create(user_message)
        self.current_task_state = task_state
        self.current_turn_id = task_state.turn_id
        self.current_run_id = task_state.run_id
        self.current_run_dir = self.run_store.start_run(task_state)
        self.session_event_bus.emit(
            "turn_started",
            {"run_id": task_state.run_id, "turn_id": task_state.turn_id},
        )
        self.session_event_bus.emit(
            "user_message",
            {
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "content": _clip(user_message, 500),
            },
        )
        self.emit_trace(
            task_state,
            "run_started",
            {
                "user_request": _clip(user_message, 500),
                "model": self.config.model,
                "tool_profile": self.tool_profile.name,
            },
        )
        return task_state

    def emit_trace(
        self,
        task_state: TaskState,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._trace_seq += 1
        record = build_runtime_event(task_state, event, payload)
        record.setdefault("span_id", f"span_{self._trace_seq:06d}")
        self.run_store.append_trace(task_state, record)
        self.run_store.write_task_state(task_state)
        return record

    def write_report(
        self,
        task_state: TaskState,
        *,
        usage: Any = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> Path:
        report = {
            **task_state.to_dict(),
            "model": self.config.model,
            "tool_profile": self.tool_profile.name,
            "usage": _usage_to_dict(usage),
            "tool_results": list(tool_results or []),
        }
        return self.run_store.write_report(task_state, report)

    def finish_task(self) -> None:
        self.current_task_state = None
        self.current_run_dir = None
        self.current_turn_id = ""
        self.current_run_id = ""


def _new_session_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"session_{timestamp}_{uuid4().hex[:8]}"


def _clip(value: str, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cost": float(getattr(usage, "cost", 0.0) or 0.0),
    }
