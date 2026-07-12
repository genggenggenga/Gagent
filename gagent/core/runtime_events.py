"""Runtime trace event helpers."""

from __future__ import annotations

from typing import Any

from gagent.core.task_state import TaskState, now_iso

PHASE_BY_EVENT = {
    "run_started": "runtime",
    "turn_started": "runtime",
    "user_message": "runtime",
    "before_model": "model",
    "model_requested": "model",
    "model_completed": "model",
    "after_model": "model",
    "tool_policy_decision": "tool",
    "permission_decision": "tool",
    "tool_started": "tool",
    "tool_finished": "tool",
    "sandbox_unavailable": "tool",
    "assistant_message": "runtime",
    "turn_finished": "runtime",
    "run_finished": "runtime",
}


def build_runtime_event(
    task_state: TaskState,
    event: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized trace event for a single run."""

    record = dict(payload or {})
    record["event"] = event
    record["created_at"] = now_iso()
    record.setdefault("trace_id", task_state.run_id)
    record.setdefault("turn_id", task_state.turn_id)
    record.setdefault("phase", PHASE_BY_EVENT.get(event, "runtime"))
    record.setdefault("status", _status_for(event, record))
    record.setdefault("duration_ms", int(record.get("duration_ms", 0) or 0))
    record.setdefault("input_chars", int(record.get("input_chars", 0) or 0))
    record.setdefault("output_chars", int(record.get("output_chars", 0) or 0))
    record.setdefault("tool_name", str(record.get("tool_name", "")))
    record.setdefault("error_type", _error_type(record))
    return record


def _status_for(event: str, payload: dict[str, Any]) -> str:
    if "status" in payload:
        return str(payload.get("status") or "")
    if event == "tool_finished":
        return "error" if payload.get("is_error") else "ok"
    if event in {"tool_policy_decision", "permission_decision"}:
        return "error" if payload.get("decision") == "deny" else "ok"
    if event == "run_finished":
        return str(payload.get("run_status") or "completed")
    if payload.get("is_error"):
        return "error"
    return "ok"


def _error_type(payload: dict[str, Any]) -> str:
    return str(
        payload.get("tool_error_code")
        or payload.get("security_event_type")
        or payload.get("error_type")
        or ""
    )
