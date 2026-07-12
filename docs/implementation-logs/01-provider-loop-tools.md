# Harness 1：Provider 抽象 + Agent Loop + Tool Use

日期：2026-07-11

## 实现范围

- 新增 Provider 抽象与 LiteLLM 接入：
  - `gagent/providers/base.py`
  - `gagent/providers/types.py`
  - `gagent/providers/litellm.py`
- 新增最小 Agent Loop：
  - `gagent/core/agent.py`
  - `gagent/core/engine.py`
  - `gagent/core/messages.py`
  - `gagent/core/prompt.py`
  - `gagent/core/runtime.py`
- 新增 session / turn 级观测最小闭环：
  - `gagent/core/session_events.py`
  - `gagent/core/task_state.py`
  - `gagent/core/run_store.py`
  - `gagent/core/runtime_events.py`
- 新增配置解析边界：
  - `gagent/config/runtime.py`
- 新增 Tool 协议、注册表、工具分级和内置工具：
  - `gagent/tools/base.py`
  - `gagent/tools/registry.py`
  - `gagent/tools/builtin/bash.py`
  - `gagent/tools/builtin/read_file.py`
  - `gagent/tools/builtin/write_file.py`
- 更新 CLI 入口：
  - `gagent/cli.py`
- 新增依赖：
  - `litellm`
  - `python-dotenv`
- 新增测试：
  - `tests/test_agent_loop.py`
  - `tests/test_tools.py`
  - `tests/test_cli.py`

## 参考来源

- Provider 层参考 AnyCoder 的 `anycoder/llm.py`：使用 LiteLLM 统一模型调用，并把流式文本、tool call、usage 和 finish reason 归一成结构化 completion result。
- Agent Loop 参考 learn-claude-code 的 s01/s02：保留“模型请求工具 -> 执行工具 -> 回填 tool result -> 继续循环”的最小闭环。
- CLI 参考 pico-v3 的 `pico/cli.py`：CLI 负责参数解析和 runtime 装配，不把业务逻辑写进入口函数。
- Tool 分级参考 pico-v3 的 `tool_profiles.py` / `tools/base.py`：每个工具带 `read_only`、`risk_level`、`category` 元数据，并通过 profile 控制模型可见工具集合。

## 当前取舍

- 第一阶段仍不做完整 Session resume，但先加入 session / turn 级观测：
  - session timeline 写入 `.gagent/sessions/<session_id>.events.jsonl`。
  - 每次用户请求写入 `.gagent/runs/<run_id>/task_state.json`、`trace.jsonl` 和 `report.json`。
  - CLI 对工具调用使用带颜色的 `[tool]` 前缀展示，便于区分模型文本和工具执行。
- 第一阶段只做工具 profile 过滤，不做完整 Permission / Sandbox 审批。
- 内置工具先保留 `bash`、`read_file`、`write_file` 三个最小集合；`edit_file`、`search`、`glob` 后续可作为 Tool Use 增强继续加入。
- Workspace 只用 `cwd` 作为路径边界，完整 `WorkspaceContext` 放到下一阶段实现。

## 结构调整

- 参考 pico-v3 的 `core/runtime.py` / `core/engine.py` 后，将第一版混在 `Agent` 类里的职责拆开：
  - `gagent/core/runtime.py`：持有 provider、tools、messages、config 等运行时状态，对应 agent runtime。
  - `gagent/core/engine.py`：负责一次用户请求的 turn-level 控制循环，对应模型调用、工具执行和事件输出。
  - `gagent/core/agent.py`：仅保留兼容导出，不再承载主循环实现。
- CLI 入口改为构建 `GagentRuntime`，在 CLI 局部以 `agent` 命名并调用 `agent.ask()`；后续接 Session、Workspace、Trace 时优先扩展 runtime，而不是把状态塞进 engine。
- Provider / Engine 边界继续收敛：
  - `LiteLLMProvider` 内部处理 streaming chunk、tool call 聚合、usage 和 `finish_reason` 归一。
  - Provider 对 Engine 返回 `ChatCompletionResult`，包含 `text`、`tool_calls`、`usage`、`stop_reason` 和 `raw_stop_reason`。
  - Engine 不再判断 `text_delta` / `tool_calls` / `usage` 事件，而是按 `stop_reason` 做 turn-level 状态机判断，更接近 pico-v3 的 Engine 分层。
- Session / Turn 级观测参考 pico-v3：
  - `GagentRuntime` 持有 `SessionEventBus`、`RunStore`、当前 `TaskState` 和 run/turn id。
  - `Engine.run_turn()` 在 `turn_started`、`model_requested`、`model_completed`、`tool_started`、`tool_finished`、`turn_finished` 等边界发事件。
  - run trace 采用 JSONL 追加写，task state 和 report 采用 JSON 原子写，便于运行中观察和运行后复盘。
  - CLI 消费 `Engine.run_turn()` 事件，使用彩色 `[tool]` 前缀打印工具开始/结束状态。
- 参考 pico-v3 的 README 项目结构，将顶层目录调整为 `cli.py`、`config/`、`core/`、`features/`、`providers/`、`tools/`、`tui/`、`evaluation/`：
  - `prompt`、`workspace`、`session`、`context`、`permission`、`runtime events` 等运行时相关能力收敛到 `core/`。
  - `sandbox`、`memory`、`skills` 等产品功能收敛到 `features/`。
  - 后续 run evidence、metrics 和 eval 相关能力进入 `evaluation/`。

## 验证记录

- `uv sync --extra dev`：已完成依赖同步，`litellm` / `python-dotenv` 可正常导入。
- `uv run pytest`：9 个测试全部通过。
- `uv run ruff check .`：通过。
- `uv run gagent --list-tools --tool-profile readonly`：能按工具 profile 只展示 `read_file`。
