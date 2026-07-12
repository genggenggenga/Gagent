# Harness 4：Hooks / Runtime Events

日期：2026-07-13

## 实现范围

- 新增 Hook 基础设施：
  - `gagent/core/hooks.py`
  - `HookManager` 支持按 hook point 注册同步 hook。
  - `HookResult` 支持 allow / deny，deny 会短路当前动作。
  - 第一版 hook point：`before_turn`、`before_model`、`after_model`、`before_tool`、`after_tool`、`before_final`。
- 新增 Runtime Consumers：
  - `gagent/core/runtime_consumers.py`
  - `DecisionReminderConsumer`：把 policy / permission deny 转为 runtime reminder。
  - `ToolStatsConsumer`：统计工具调用次数、错误数、耗时。
  - `ChangedPathConsumer`：根据成功写工具维护 `changed_paths`。
- 增强 Runtime Event：
  - `gagent/core/runtime_events.py`
  - 增加 policy / permission / sandbox / turn 相关事件 phase 和 status 归一。
  - 增加 `error_type`、`tool_name` 等通用字段。
- Runtime 统一事件入口：
  - `GagentRuntime.emit_event()` 统一负责写 session timeline、run trace，并分发给 runtime consumers。
  - `session_started`、`run_started`、`model_requested`、`tool_finished`、`run_finished` 等事件统一走该入口。
- Permission / Policy hook 化：
  - `ToolPolicyChecker` 和 `PermissionChecker` 被注册为 mandatory `before_tool` hooks。
  - `ToolPolicyChecker.record_result()` 被注册为 mandatory `after_tool` hook。
  - 安全 gate 仍默认强制执行，不作为可选插件。
- Engine 瘦身：
  - Engine 不再直接同时调用 `session_event_bus.emit()` 和 `emit_trace()`。
  - Engine 只推进 turn loop，并通过 `runtime.emit_event()` 发出生命周期事件。
- 扩展测试：
  - `tests/test_hooks.py`
  - 更新 `tests/test_agent_loop.py`

## 参考来源

- learn-claude-code `s04_hooks/code.py`：
  - 将 s03 的 permission 从 loop 里移到 `PreToolUse` hook。
  - 提供 `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop` 的教学型 hook point。
- pico-v3 `core/runtime_events.py`：
  - 结构化 runtime trace event，包含 phase、status、duration、error_type 等字段。
- pico-v3 `core/session_events.py`：
  - session timeline 单独持久化，和 run trace 分离。
- pico-v3 `core/runtime_consumers.py`：
  - 用消费者从事件派生 artifact graph、verification suggestion、runtime reminder 等状态。

## 当前取舍

- Hook 系统只支持同步 Python hook：
  - 暂不支持外部命令 hook、配置文件 hook 或异步 hook。
  - 后续 Slash Command / Skills 阶段再考虑用户可配置扩展。
- Permission / Policy 是 mandatory hooks：
  - 它们被 hook 化是为了统一生命周期和减少 Runtime 分支。
  - 但它们不是可选插件，不能通过普通配置关闭。
- Sandbox 仍是 bash runner backend：
  - sandbox 负责“如何执行 bash”，不是普通 hook。
  - sandbox 事件仍通过 `runtime.emit_event()` 进入统一事件流。
- `emit_trace()` 暂时保留：
  - 兼容已有调用和测试。
  - 新代码优先使用 `emit_event()`。

## 验证记录

- `/Users/bytedance/.local/bin/uv run pytest -q`：38 个测试全部通过。
- `/Users/bytedance/.local/bin/uv run ruff check`：通过。
