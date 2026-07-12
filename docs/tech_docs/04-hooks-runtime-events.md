# Harness 4 技术设计：Hooks / Runtime Events

## 背景与目标

Harness 4 的目标是让 Gagent 的主循环继续保持简洁：Engine 只负责推进 turn-level 控制流，检查、补救、通知、状态派生等逻辑挂到 hook 和 runtime event 管线中。

这一阶段解决三个问题：

- Engine 中不再散落 session/trace 双写。
- Permission / Policy 进入 mandatory hook 管线。
- 运行事件统一进入 consumers，用于派生状态和提醒。

## 总体架构

```text
Engine
  -> Runtime.run_hooks(...)
  -> Runtime.emit_event(...)
      -> SessionEventBus
      -> RunStore trace
      -> RuntimeConsumers

Runtime.run_tool()
  -> before_tool hooks
      -> ToolPolicyHook
      -> PermissionHook
  -> ToolRegistry.execute()
  -> after_tool hooks
      -> ToolPolicyStateHook
  -> Runtime.emit_event("tool_finished")
```

核心原则：

- Engine 只推进流程。
- Runtime 是生命周期事件和工具执行边界。
- Hooks 提供扩展点。
- Consumers 从事件派生状态。

## Hook 系统

实现位于 `gagent/core/hooks.py`。

核心类型：

```python
HookPoint = Literal[
    "before_turn",
    "before_model",
    "after_model",
    "before_tool",
    "after_tool",
    "before_final",
]
```

```python
@dataclass(frozen=True)
class HookContext:
    runtime: Any
    point: HookPoint
    payload: dict[str, Any]
```

```python
@dataclass(frozen=True)
class HookResult:
    allowed: bool
    reason: str
    message: str
    metadata: dict[str, Any]
```

`HookManager` 提供：

- `register(point, hook, name, mandatory)`
- `run(point, context)`
- `names_for(point)`

当前只支持同步 Python hook，不支持外部命令或异步 hook。

## Hook Points

### before_turn

用户请求进入 turn 后触发。

适合：

- 注入上下文提醒
- 初始化 per-turn 状态
- 后续 slash command 或 task state 扩展

### before_model

调用 provider 前触发。

适合：

- 检查上下文窗口
- 后续 compact 触发
- 模型调用前审计

### after_model

模型返回后触发。

适合：

- 统计模型输出
- 记录 stop_reason
- 后续 error recovery 分析

### before_tool

工具执行前触发。

当前 mandatory hooks：

- ToolPolicyHook
- PermissionHook

如果 hook deny，工具不会执行，并返回结构化 tool error。

### after_tool

工具执行后触发。

当前 mandatory hook：

- ToolPolicyStateHook：记录 fresh read / mutation state。

后续可扩展：

- 大输出保存 artifact
- 自动格式化
- 变更路径统计

### before_final

最终回答前触发。

当前只是预留，后续适合：

- final readiness check
- verification hint
- 自动提醒模型先运行测试

## Mandatory Hooks

Permission / Policy 被 hook 化，但仍是强制安全边界。

```text
before_tool:
  ToolPolicyHook
  PermissionHook

after_tool:
  ToolPolicyStateHook
```

设计理由：

- 统一生命周期扩展模型。
- 减少 `GagentRuntime.run_tool()` 中的硬编码分支。
- 保持安全能力默认强制执行，不让普通配置关闭。

Sandbox 不作为普通 hook，因为它负责 bash 的执行方式，而不是工具是否允许执行。

## Runtime Events

实现位于 `gagent/core/runtime_events.py`。

Runtime event 是统一 trace 事件格式。

典型字段：

```python
{
    "event": "tool_finished",
    "phase": "tool",
    "status": "ok",
    "run_id": "...",
    "turn_id": "...",
    "span_id": "span_000001",
    "duration_ms": 12,
    "tool_name": "read_file",
    "output_chars": 1200,
    "error_type": "",
}
```

事件会根据类型自动归一：

- phase：runtime / model / tool
- status：ok / error / completed
- error_type：来自 `tool_error_code` 或 `security_event_type`

## Runtime.emit_event()

统一事件入口位于 `GagentRuntime.emit_event()`。

职责：

```text
1. 写 session timeline
2. 写 run trace
3. 分发给 runtime consumers
4. 写回 task_state
```

这样 Engine 不再直接调用：

```python
session_event_bus.emit(...)
emit_trace(...)
```

而是统一：

```python
runtime.emit_event("model_requested", payload)
```

## Session Timeline 与 Run Trace

两者职责不同：

```text
session timeline:
  .gagent/sessions/<session_id>.events.jsonl
  记录整个交互 session 的粗粒度时间线

run trace:
  .gagent/runs/<run_id>/trace.jsonl
  记录单次任务的细粒度诊断事件
```

`emit_event()` 会同时写两者。如果当前还没有 active task，则只写 session timeline。

## Runtime Consumers

实现位于 `gagent/core/runtime_consumers.py`。

Consumers 不负责写事件，而是监听事件并派生状态。

当前默认 consumers：

### DecisionReminderConsumer

监听：

- `tool_policy_decision`
- `permission_decision`

当 decision 为 deny 时，把信息写入：

```python
task_state.runtime_reminders
```

后续可用于提醒模型换策略。

### ToolStatsConsumer

监听：

- `tool_finished`

维护：

```python
task_state.tool_stats
```

记录每个工具的调用次数、错误数和累计耗时。

### ChangedPathConsumer

监听成功的写工具：

- `write_file`
- `edit_file`

维护：

```python
task_state.changed_paths
```

后续可用于 verification suggestion、最终总结和 session resume。

## Engine 瘦身

Harness 4 后，Engine 仍负责：

- append user/assistant/tool messages
- 调用 provider
- 根据 stop_reason 分支
- 调用 Runtime 执行工具
- yield UI event

Engine 不再负责：

- 分别写 session event
- 分别写 run trace
- 派生 runtime reminders
- 更新 changed paths

这些都下沉到 Runtime / Consumers。

## 当前取舍

- Hook 系统只支持同步 hook。
- 不支持用户自定义配置文件 hook。
- 不支持外部命令 hook。
- `emit_trace()` 暂时保留用于兼容，新代码优先使用 `emit_event()`。
- before_final 只预留 hook point，暂不做 final readiness check。

## 后续演进

- TodoWrite 阶段可以用 runtime events 更新任务进度。
- Session Resume 阶段可以保存/恢复 `changed_paths`、`tool_stats` 和 reminders。
- Compact 阶段可在 `before_model` hook 检查上下文压力。
- Error Recovery 阶段可消费 denied decision 和 failed tool stats 生成重试策略。
- Skills 阶段可注册按需加载的 domain hooks。
