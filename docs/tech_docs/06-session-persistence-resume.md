# Harness 6 技术设计：Session 持久化 / Resume

## 背景与目标

Harness 6 的目标是给 Gagent 增加最小可恢复会话能力：CLI 重启后可以恢复同一段对话，继续沿用历史 `messages`、session timeline、最近 todo snapshot 和 run 关联关系。

这一阶段只实现轻量 session model，不实现 checkpoint、fork、compact、memory 或复杂 workspace 快照。

## 参考模型

```text
pico:
  SessionStore.save/load/latest -> .pico/sessions/<session_id>.json

pico-v3:
  session JSON       -> 可恢复状态
  session events     -> timeline
  run artifacts      -> 单次请求诊断
  checkpoints        -> 更重的恢复与验证
```

Gagent 采用 pico-v3 的职责划分，但只落地当前必须的 session JSON：

- `.gagent/sessions/<session_id>.json`：可恢复对话状态。
- `.gagent/sessions/<session_id>.events.jsonl`：session timeline，沿用已有 `SessionEventBus`。
- `.gagent/runs/<run_id>/...`：单次 turn 的诊断产物，沿用已有 `RunStore`。

## 文件与模块边界

新增或补全的核心模块：

```text
gagent/core/session.py        # SessionState 数据模型
gagent/core/session_store.py  # SessionStore JSON 持久化
gagent/core/runtime.py        # load/create/save session，与 Runtime 生命周期绑定
gagent/cli.py                 # --resume / --list-sessions
```

职责边界：

- `SessionState` 只描述可序列化状态。
- `SessionStore` 只负责 session JSON 的读写、latest、list。
- `GagentRuntime` 负责把 session 绑定到当前 provider/tools/workspace/system prompt。
- `Engine` 不直接理解 session 格式，只在 turn 收尾时通过 `runtime.write_report()` 间接触发 `save_session()`。

## Session Schema

当前 schema version 为 `1`：

```json
{
  "schema_version": 1,
  "id": "session_20260721-013000_a1b2c3d4",
  "created_at": "2026-07-21T01:30:00.000+00:00",
  "updated_at": "2026-07-21T01:31:00.000+00:00",
  "workspace": {
    "cwd": "/path/to/workspace",
    "repo_root": "/path/to/workspace",
    "fingerprint": "sha256..."
  },
  "model": "deepseek/deepseek-chat",
  "system_prompt_hash": "sha256...",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "todos": [
    {"content": "Implement session persistence", "status": "in_progress"}
  ],
  "run_ids": ["run_20260721-013000_a1b2c3d4"]
}
```

字段说明：

- `messages` 是 resume 的核心，保持 OpenAI-compatible message 格式。
- `todos` 保存最近一次 turn 的 todo snapshot。
- `run_ids` 关联该 session 下产生过的 run artifacts。
- `workspace.fingerprint` 记录创建或最近保存 session 时的 workspace prompt fingerprint。
- `system_prompt_hash` 用于判断 resume 时 system prompt 是否需要刷新。

## Runtime 生命周期

新 session：

```text
GagentRuntime.__init__
  -> build WorkspaceContext
  -> build system prompt
  -> SessionStore(.gagent/sessions)
  -> SessionState.create(messages=[system])
  -> SessionEventBus(<session_id>.events.jsonl)
  -> emit session_started
  -> save_session()
```

恢复 session：

```text
GagentRuntime.__init__(session_id=... or resume_latest=True)
  -> SessionStore.load()
  -> compare workspace repo_root
  -> compare system_prompt_hash
  -> refresh first system message if changed
  -> bind runtime.messages = session.messages
  -> SessionEventBus(existing <session_id>.events.jsonl)
  -> emit session_resumed
```

每个 turn 结束：

```text
Engine._record_turn_finished()
  -> runtime.write_report(task_state, ...)
      -> RunStore.write_report()
      -> runtime.save_session(task_state)
          -> messages
          -> latest todos
          -> run_ids
          -> workspace/model/system_prompt_hash
```

## Resume 行为

CLI 支持：

```bash
gagent --resume latest
gagent --resume session_20260721-013000_a1b2c3d4
gagent --list-sessions
```

`--resume latest` 使用 `.gagent/sessions/*.json` 中最近修改的 session。

`--resume <id>` 加载指定 session JSON，并继续向同一个 `.events.jsonl` 追加 timeline。

`--list-sessions` 输出 session id、更新时间、message 数、run 数和最后一条用户消息预览。

## System Prompt 与 Workspace 处理

恢复时只做轻量校验：

- `repo_root` 不一致：记录 `resume_warnings`，并在 `session_resumed` event 中保存 warning，不阻断。
- `system_prompt_hash` 不一致：刷新 `messages[0]` 的 system message，保留后续历史消息。
- session JSON 不存在、损坏或 schema version 不支持：直接抛出明确错误。

这里不做 workspace file snapshot diff。完整 checkpoint/freshness 检查留给后续阶段。

## 与 TodoWrite 的关系

`TodoStateConsumer` 仍然只更新当前 `TaskState`。

Session 阶段新增一条持久化链路：

```text
todo_write
  -> TodoStateConsumer updates task_state.todos
  -> write_report()
  -> save_session(task_state)
  -> session.todos = task_state.todos
```

下一次 resume 后，`runtime.session.todos` 会保留最近 snapshot；新 turn 的 `TaskState` 会从 session todos 初始化，保证 run artifact 能延续最近任务进度。

## 当前取舍

本阶段不实现：

- checkpoint / fork。
- context compact。
- message 裁剪或 token budget 管理。
- session schema migration 框架。
- workspace 文件级 freshness。
- 多进程并发锁。
- memory 持久化。

这些能力依赖更明确的 context 和 task system 设计，后续再引入更稳。

## 测试覆盖

新增测试覆盖：

- Runtime 初始化会创建 session JSON。
- turn 结束后 session JSON 包含最新 messages 和 run id。
- `--resume <id>` 会把历史 messages 传给 provider。
- `--resume latest` 会恢复最近 session。
- system prompt hash 变化时刷新第一条 system message。
- todo snapshot 会进入 session JSON，并可在 resume 后读取。
- CLI 可解析 resume 参数并输出 session 列表。
