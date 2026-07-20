"""Runtime state and dependency composition for Gagent."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from gagent.core.engine import AgentRunResult, Engine, TextSink
from gagent.core.hooks import HookContext, HookManager, HookPoint, HookResult
from gagent.core.messages import system_message
from gagent.core.permissions import ApprovalPolicy, PermissionChecker
from gagent.core.prompt import build_system_prompt
from gagent.core.run_store import RunStore
from gagent.core.runtime_consumers import RuntimeConsumer, default_runtime_consumers
from gagent.core.runtime_events import build_runtime_event
from gagent.core.session import SessionState
from gagent.core.session_events import SessionEventBus
from gagent.core.session_store import SessionStore
from gagent.core.task_state import TaskState
from gagent.core.tool_policy import ToolPolicyChecker
from gagent.core.workspace import WorkspaceContext
from gagent.features.sandbox import SandboxBackend, SandboxConfig, SandboxMode, SandboxRunner
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
    approval_policy: ApprovalPolicy = "auto"
    sandbox_mode: SandboxMode = "off"
    sandbox_backend: SandboxBackend = "auto"
    sandbox_workspace_write: bool = True


class GagentRuntime:
    """Runtime object that owns state and delegates turn execution to Engine."""

    def __init__(
        self,
        *,
        provider: Provider,
        config: AgentConfig,
        tools: ToolRegistry | None = None,
        messages: list[dict] | None = None,
        runtime_consumers: list[RuntimeConsumer] | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
    ) -> None:
        self.provider = provider
        self.config = config
        self.tools = tools or build_builtin_registry()
        self.tool_profile = resolve_tool_profile(self.tools, config.tool_profile)
        self.workspace = WorkspaceContext.build(config.cwd)
        self.permission_checker = PermissionChecker(approval_policy=config.approval_policy)
        self.tool_policy_checker = ToolPolicyChecker()
        self.system_prompt = build_system_prompt(
            workspace=self.workspace,
            tools=self.tools,
            profile=self.tool_profile,
        )
        self.session_dir = config.cwd / ".gagent" / "sessions"
        self.session_store = SessionStore(self.session_dir)
        self.resume_warnings: list[str] = []
        self.session = self._load_or_create_session(
            messages=messages,
            session_id=session_id,
            resume_latest=resume_latest,
        )
        self.messages = [dict(message) for message in self.session.messages]
        self.session_id = self.session.id
        self.run_store = RunStore(config.cwd / ".gagent" / "runs")
        self.session_event_bus = SessionEventBus(
            session_id=self.session_id,
            path=self.session_store.event_path(self.session_id),
        )
        self.current_task_state: TaskState | None = None
        self.current_run_dir: Path | None = None
        self.current_turn_id = ""
        self.current_run_id = ""
        self._trace_seq = 0
        self.runtime_consumers = runtime_consumers or default_runtime_consumers()
        self.hooks = HookManager()
        self._register_default_hooks()
        self.sandbox_runner = SandboxRunner(
            SandboxConfig(
                mode=config.sandbox_mode,
                backend=config.sandbox_backend,
                workspace_write=config.sandbox_workspace_write,
            ),
            emit_event=self._emit_sandbox_event,
        )
        self.tool_context = ToolExecutionContext(
            cwd=config.cwd,
            workspace=self.workspace,
            sandbox_runner=self.sandbox_runner,
        )
        if session_id or resume_latest:
            self.emit_event(
                "session_resumed",
                {
                    "workspace_root": str(self.workspace.repo_root),
                    "cwd": str(self.workspace.cwd),
                    "model": config.model,
                    "system_prompt_hash": self.system_prompt.hash,
                    "warnings": list(self.resume_warnings),
                },
            )
        else:
            self.emit_event(
                "session_started",
                {
                    "workspace_root": str(self.workspace.repo_root),
                    "cwd": str(self.workspace.cwd),
                    "model": config.model,
                    "system_prompt_hash": self.system_prompt.hash,
                },
            )
            self.save_session()
        self.engine = Engine(self)

    def ask(self, user_message: str, *, on_text: TextSink | None = None) -> AgentRunResult:
        return self.engine.ask(user_message, on_text=on_text)

    def tool_schemas(self) -> list[dict]:
        return self.tools.schemas_for_profile(self.tool_profile)

    def save_session(self, task_state: TaskState | None = None) -> Path:
        """Persist the resumable conversation state."""

        self.session.messages = [dict(message) for message in self.messages]
        self.session.workspace = self._workspace_record()
        self.session.model = self.config.model
        self.session.system_prompt_hash = self.system_prompt.hash
        if task_state is not None:
            self.session.todos = [dict(todo) for todo in task_state.todos]
            if task_state.run_id and task_state.run_id not in self.session.run_ids:
                self.session.run_ids.append(task_state.run_id)
        return self.session_store.save(self.session)

    def run_hooks(self, point: HookPoint, payload: dict[str, Any] | None = None) -> HookResult:
        return self.hooks.run(
            point,
            HookContext(runtime=self, point=point, payload=dict(payload or {})),
        )

    def run_tool(self, tool_call: ToolCall) -> dict:
        tool = self.tools.get(tool_call.name)
        if tool is None:
            return self._tool_result(
                tool_call,
                content=f"error: unknown tool '{tool_call.name}'",
                is_error=True,
                metadata={"tool_error_code": "unknown_tool"},
            )
        before_result = self.hooks.run(
            "before_tool",
            HookContext(
                runtime=self,
                point="before_tool",
                payload={"tool": tool, "tool_call": tool_call, "args": tool_call.arguments},
            ),
        )
        if not before_result.allowed:
            return self._tool_result(
                tool_call,
                content=before_result.message,
                is_error=True,
                metadata={
                    "tool_error_code": before_result.metadata.get(
                        "tool_error_code", before_result.reason
                    ),
                    **before_result.metadata,
                },
            )

        result = self.tools.execute(
            tool_call.name,
            tool_call.arguments,
            self.tool_context,
            self.tool_profile,
        )
        self.hooks.run(
            "after_tool",
            HookContext(
                runtime=self,
                point="after_tool",
                payload={
                    "tool": tool,
                    "tool_call": tool_call,
                    "args": tool_call.arguments,
                    "result": result,
                },
            ),
        )
        return self._tool_result(
            tool_call,
            content=result.content,
            is_error=result.is_error,
            metadata=result.metadata or {},
        )

    def start_task(self, user_message: str) -> TaskState:
        task_state = TaskState.create(user_message)
        task_state.todos = [dict(todo) for todo in self.session.todos]
        self.current_task_state = task_state
        self.current_turn_id = task_state.turn_id
        self.current_run_id = task_state.run_id
        self.current_run_dir = self.run_store.start_run(task_state)
        self.emit_event(
            "turn_started",
            {"run_id": task_state.run_id, "turn_id": task_state.turn_id},
        )
        self.emit_event(
            "user_message",
            {
                "run_id": task_state.run_id,
                "turn_id": task_state.turn_id,
                "content": _clip(user_message, 500),
            },
        )
        self.emit_event(
            "run_started",
            {
                "user_request": _clip(user_message, 500),
                "model": self.config.model,
                "tool_profile": self.tool_profile.name,
            },
        )
        return task_state

    def emit_event(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Emit one runtime event to session timeline, run trace, and consumers."""

        enriched = {
            "run_id": self.current_run_id,
            "turn_id": self.current_turn_id,
            **dict(payload or {}),
        }
        session_record = self.session_event_bus.emit(event, enriched)
        if self.current_task_state is None:
            return session_record

        self._trace_seq += 1
        trace_record = build_runtime_event(self.current_task_state, event, enriched)
        trace_record.setdefault("span_id", f"span_{self._trace_seq:06d}")
        self.run_store.append_trace(self.current_task_state, trace_record)
        for consumer in self.runtime_consumers:
            consumer.handle(self, self.current_task_state, trace_record)
        self.run_store.write_task_state(self.current_task_state)
        return trace_record

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
        path = self.run_store.write_report(task_state, report)
        self.save_session(task_state)
        return path

    def finish_task(self) -> None:
        self.current_task_state = None
        self.current_run_dir = None
        self.current_turn_id = ""
        self.current_run_id = ""

    def _register_default_hooks(self) -> None:
        self.hooks.register(
            "before_tool",
            self._tool_policy_hook,
            name="tool_policy",
            mandatory=True,
        )
        self.hooks.register(
            "before_tool",
            self._permission_hook,
            name="permission",
            mandatory=True,
        )
        self.hooks.register(
            "after_tool",
            self._tool_policy_state_hook,
            name="tool_policy_state",
            mandatory=True,
        )

    def _tool_policy_hook(self, context: HookContext) -> HookResult:
        tool = context.payload["tool"]
        args = context.payload["args"]
        decision = self.tool_policy_checker.check(tool, args, self.tool_context)
        self.emit_event(
            "tool_policy_decision",
            {
                "tool_name": tool.name,
                "decision": decision.decision,
                "reason": decision.reason,
                "message": decision.message,
            },
        )
        if decision.allowed:
            return HookResult.allow(decision.reason)
        return HookResult.deny(
            decision.reason,
            message=decision.message,
            metadata={"tool_error_code": decision.reason},
        )

    def _permission_hook(self, context: HookContext) -> HookResult:
        tool = context.payload["tool"]
        args = context.payload["args"]
        decision = self.permission_checker.check(
            tool,
            args,
            self.tool_context,
            self.tool_profile,
        )
        self.emit_event(
            "permission_decision",
            {
                "tool_name": tool.name,
                "decision": decision.decision,
                "reason": decision.reason,
                "security_event_type": decision.security_event_type,
                "message": decision.message,
            },
        )
        if decision.allowed:
            return HookResult.allow(decision.reason)
        return HookResult.deny(
            decision.reason,
            message=decision.message or f"error: permission denied for {tool.name}",
            metadata={"tool_error_code": decision.reason},
        )

    def _tool_policy_state_hook(self, context: HookContext) -> HookResult:
        tool = context.payload["tool"]
        args = context.payload["args"]
        result = context.payload["result"]
        self.tool_policy_checker.record_result(
            tool,
            args,
            self.tool_context,
            is_error=result.is_error,
        )
        return HookResult.allow("tool_policy_state_recorded")

    def _tool_result(
        self,
        tool_call: ToolCall,
        *,
        content: str,
        is_error: bool,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return {
            "id": tool_call.id,
            "name": tool_call.name,
            "is_error": is_error,
            "content": content,
            "metadata": metadata or {},
        }

    def _emit_decision_event(
        self,
        event: str,
        tool_name: str,
        decision: str,
        reason: str,
        *,
        security_event_type: str = "",
    ) -> None:
        payload = {
            "run_id": self.current_run_id,
            "turn_id": self.current_turn_id,
            "tool_name": tool_name,
            "decision": decision,
            "reason": reason,
            "security_event_type": security_event_type,
        }
        self.emit_event(event, payload)

    def _emit_sandbox_event(self, event: str, payload: dict) -> None:
        self.emit_event(event, payload)

    def _load_or_create_session(
        self,
        *,
        messages: list[dict] | None,
        session_id: str | None,
        resume_latest: bool,
    ) -> SessionState:
        if session_id or resume_latest:
            resolved_session_id = session_id
            if resume_latest:
                resolved_session_id = self.session_store.latest()
                if resolved_session_id is None:
                    raise ValueError("no session available to resume")
            session = self.session_store.load(str(resolved_session_id))
            self._prepare_resumed_session(session)
            return session

        initial_messages = messages or [system_message(self.system_prompt.text)]
        return SessionState.create(
            session_id=_new_session_id(),
            workspace=self._workspace_record(),
            model=self.config.model,
            system_prompt_hash=self.system_prompt.hash,
            messages=initial_messages,
        )

    def _prepare_resumed_session(self, session: SessionState) -> None:
        recorded_root = session.workspace.get("repo_root", "")
        if recorded_root and recorded_root != str(self.workspace.repo_root):
            self.resume_warnings.append(
                f"workspace mismatch: session={recorded_root}, current={self.workspace.repo_root}"
            )

        system_prompt_changed = session.system_prompt_hash != self.system_prompt.hash
        if system_prompt_changed:
            self.resume_warnings.append("system prompt changed; refreshed the system message")
            current_system = system_message(self.system_prompt.text)
            if session.messages and session.messages[0].get("role") == "system":
                session.messages[0] = current_system
            else:
                session.messages.insert(0, current_system)

        if not session.messages:
            session.messages = [system_message(self.system_prompt.text)]
        session.workspace = self._workspace_record()
        session.model = self.config.model
        session.system_prompt_hash = self.system_prompt.hash
        self.session_store.save(session)

    def _workspace_record(self) -> dict[str, str]:
        return {
            "cwd": str(self.workspace.cwd),
            "repo_root": str(self.workspace.repo_root),
            "fingerprint": self.workspace.fingerprint(),
        }


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
