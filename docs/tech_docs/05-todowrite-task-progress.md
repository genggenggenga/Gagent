# Harness 5 技术设计：TodoWrite / Task Progress State

## 背景与目标

Harness 5 的目标是给 Gagent 增加最小任务进度控制面：复杂任务先拆成步骤，执行过程中持续更新状态，运行后可以从 `task_state.json` 和 `report.json` 复盘任务推进情况。

这一阶段不引入完整 Task System，也不做跨 session 任务看板，只实现当前 run 内的轻量 `todo_write`。

## 参考模型

```text
learn-claude-code s05:
  todo_write(todos) -> 更新当前进程内存列表

pico-v3:
  TodoLedger -> session state
  todo_changes -> TaskState / report
```

Gagent 当前采用折中方案：

- 工具形态采用 learn-claude-code 的单个 `todo_write`。
- 状态落盘采用 pico-v3 的 task_state/report 思路。

## Tool Contract

工具名：

```text
todo_write
```

Schema：

```python
{
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                    },
                },
                "required": ["content", "status"],
            },
        }
    },
    "required": ["todos"],
}
```

语义：

- 一次性替换当前任务进度列表。
- 不读取文件。
- 不修改 workspace 文件。
- 不执行 shell。
- 返回当前 todo 列表的可读文本。

## 状态模型

Todo item 当前只包含两个字段：

```python
{
    "content": "Implement todo tool",
    "status": "in_progress",
}
```

状态集合：

- `pending`：尚未开始。
- `in_progress`：当前正在做。
- `completed`：已完成。

约束：

- `content` 不能为空。
- `status` 必须在合法集合内。
- 最多只能有一个 `in_progress`。

不引入 `id`、`priority`、`note`，是为了保持最小实现。后续如果要做局部 update 或跨 session ledger，再补稳定 id。

## Runtime 数据流

```text
LLM tool_call(todo_write)
  -> ToolRegistry.execute()
  -> todo_write runner validates todos
  -> ToolResult(content, metadata={todos, todo_counts})
  -> Engine emits tool_finished
  -> Runtime.emit_event()
  -> TodoStateConsumer
      -> task_state.todos = todos
      -> task_state.todo_changes.append(...)
  -> RunStore writes task_state.json
  -> finish writes report.json
```

核心点：`todo_write` 工具本身只负责校验和返回 metadata；状态写入由 runtime consumer 完成。这样工具实现不需要知道 Runtime，也符合 Hooks / Runtime Events 阶段确立的事件管线。

## TaskState 扩展

`TaskState` 新增：

```python
todos: list[dict[str, str]]
todo_changes: list[dict[str, object]]
```

`todos` 表示当前任务进度快照。

`todo_changes` 表示本 run 中 todo 被写入的历史：

```python
{
    "action": "write",
    "todos": [...],
    "counts": {
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
    },
    "created_at": "...",
}
```

这些字段通过 `TaskState.to_dict()` 自动进入：

- `.gagent/runs/<run_id>/task_state.json`
- `.gagent/runs/<run_id>/report.json`

## Tool Profile

`todo_write` 的元数据：

```python
category = "read"
risk_level = "low"
```

理由：

- 它不读写 workspace 文件。
- 它不执行外部命令。
- 它只改变 Gagent 的运行内 progress state。

因此它会出现在：

- `default`
- `readonly`
- `no_shell`

## Prompt Guidance

System Prompt 增加规则：

```text
For multi-step work, use todo_write to create a short task list before acting.
Keep todos current: exactly one active step should be in_progress when work is underway.
```

这里不把当前 todo 列表动态塞回 system prompt。当前最小实现依赖两条路径：

- `todo_write` 的 tool result 会进入消息历史，下一轮模型可见。
- `task_state/report` 会落盘，供用户和后续能力复盘。

后续 Session / Context 阶段可以把当前 todo snapshot 作为动态 context section 注入。

## 当前取舍

- 不做 `todo_add/update/list`。
- 不做跨 session todo ledger。
- 不做固定 round counter reminder。
- 不做 final 前 todo completion gate。
- 不做 todo id 和局部 patch 更新。

这些都适合后续在 Session、Hooks、Context Compact 或 Task System 阶段逐步补。

## 后续演进

- Hooks 阶段可增加 `before_final` todo gate：未完成 todo 需要说明 blocked reason 或 continuation plan。
- Session 阶段可把 todo snapshot 存到 session state，支持 resume。
- Context Compact 阶段可把 todo 作为高优先级保留 section。
- Task System 阶段再引入 id、dependency、owner、blocked reason 和跨 session 持久化。
