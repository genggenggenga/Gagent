# Harness 5：TodoWrite / Task Progress State

日期：2026-07-21

## 实现范围

- 新增 TodoWrite 工具：
  - `gagent/tools/builtin/todo_write.py`
  - 工具名：`todo_write`
  - 参数：`todos: list[{content: str, status: pending|in_progress|completed}]`
  - 语义：一次性替换当前任务进度列表，不执行任何文件或 shell 操作。
- Tool Registry 接入：
  - `gagent/tools/registry.py`
  - `todo_write` 注册进默认内置工具集合。
  - 因为它只更新运行状态，不读写文件、不执行命令，所以归类为 `category=read`、`risk_level=low`，会出现在 `readonly` profile 中。
- TaskState 扩展：
  - `gagent/core/task_state.py`
  - 新增 `todos`
  - 新增 `todo_changes`
  - `task_state.json` 和 `report.json` 自动包含当前 todo 列表和变更记录。
- Runtime Consumer 接入：
  - `gagent/core/runtime_consumers.py`
  - 新增 `TodoStateConsumer`
  - 消费成功的 `tool_finished(todo_write)` 事件，将 `metadata.todos` 写入 `TaskState.todos`，并追加 `todo_changes`。
- System Prompt 更新：
  - `gagent/core/prompt.py`
  - 增加多步任务先用 `todo_write` 规划、运行中保持状态更新的行为规则。
- 新增 / 更新测试：
  - `tests/test_tools.py`
  - `tests/test_agent_loop.py`
  - `tests/test_prompt.py`

## 参考来源

- learn-claude-code `s05_todo_write/code.py`：
  - 采用单个 `todo_write` 工具。
  - 工具只维护当前进度列表，不提供额外执行能力。
  - 状态采用 `pending`、`in_progress`、`completed`。
- pico-v3 `core/todo_ledger.py` / `tools/todos.py`：
  - todo 不只是 UI 装饰，应进入 task state / report / prompt context。
  - todo 变更需要可复盘。

## 当前取舍

- 选择最简单的 `todo_write`，不实现 `todo_add` / `todo_update` / `todo_list` 三工具。
- Todo 状态是 run-level progress state：
  - 当前写入 `TaskState` 和 report。
  - 暂不做跨 session 持久 ledger。
- `todo_write` 不作为写工具：
  - 它不修改 workspace 文件。
  - 可以在 `readonly` profile 下使用。
- 强制最多一个 `in_progress`：
  - 防止模型同时标记多个正在进行的步骤。
  - 保持任务进度线性可读。
- 不实现 s05 教学版的固定“三轮未更新 reminder”：
  - 当前已经有 Hooks / Runtime Events。
  - 后续可以用 hook/consumer 做更稳的 reminder，而不是写死 round counter。

## 验证记录

- `/Users/bytedance/.local/bin/uv run pytest -q`：41 个测试全部通过。
- `/Users/bytedance/.local/bin/uv run ruff check`：通过。
