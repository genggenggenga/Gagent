# Harness 7 技术设计：Slash Commands

## 背景与目标

Harness 7 的目标是给 Gagent 增加最小 REPL 控制面：用户输入以 `/` 开头的命令时，CLI 直接处理，不进入 LLM，不写入 `runtime.messages`，也不触发 tool loop。

本阶段先暴露：

- `/help`
- `/status`
- `/tools`
- `/clear`
- `/exit`
- `/quit`

后续 Context Compact 阶段再自然扩展 `/compact`。

## 参考模型

```text
pico-v3:
  pico/commands/slash.py -> SlashCommand registry / resolve / suggest
  pico/cli.py            -> handle_repl_command(agent, user_input)

learn-claude-code s_full:
  REPL 内联 if query == "/compact"
```

Gagent 采用 pico-v3 的分层思路，但只实现当前 CLI 需要的最小命令集合。`learn-claude-code` 的内联判断适合教学 demo，不适合作为长期扩展结构。

## 模块边界

新增模块：

```text
gagent/commands/__init__.py
gagent/commands/slash.py
```

职责：

- `gagent/commands/slash.py`：只保存命令元数据和解析能力。
- `gagent/cli.py`：实现 `handle_repl_command()`，把命令映射到 CLI/runtime 行为。
- `gagent/core/runtime.py`：提供 `clear_session()`，避免 CLI 直接拼装 Runtime 内部状态。

Slash command 不是 tool：

- 不进入 `ToolRegistry`。
- 不出现在 provider tool schema。
- 不经过 permission/sandbox。
- 不由 LLM 触发。

它是用户本地 REPL 控制面。

## Command Registry

命令元数据：

```python
@dataclass(frozen=True)
class SlashCommand:
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()
```

当前 registry：

```text
/help      Show available slash commands.
/status    Show current runtime and session status.
/tools     List tools available in the current tool profile.
/clear     Create a new empty session.
/exit      Exit the interactive REPL.
/quit      Alias of /exit.
```

解析函数：

- `resolve_command(name)`：支持命令名和 alias。
- `command_help_text()`：渲染 `/help` 文本。
- `suggest_commands(text)`：为后续 TUI/补全预留，但当前 CLI 不使用。

## CLI 数据流

REPL 主循环：

```text
input()
  -> handle_repl_command(agent, user_input)
      -> handled=True  => print output / exit
      -> handled=False => run_agent_turn(agent, user_input)
```

one-shot prompt 也复用同一入口：

```text
gagent /status
  -> handle_repl_command()
  -> print status
  -> no provider call
```

未知 `/xxx` 会被 slash command handler 消费：

```text
Unknown command: /xxx. Use /help.
```

这样可以避免用户手误的 slash command 被当作普通 prompt 发给模型。

## `/status`

`/status` 输出当前 runtime/session 的核心状态：

```text
session id: ...
session path: ...
events path: ...
cwd: ...
repo root: ...
model: ...
tool profile: ...
messages: ...
todos: pending=0 in_progress=0 completed=0
last run id: ...
last run dir: ...
```

该命令只读内存和已知路径，不读写 workspace 文件。

## `/tools`

`/tools` 展示当前 `tool_profile` 下可用工具：

```text
read_file   read    Read a workspace file...
todo_write  read    Create or replace current task progress list...
```

它使用：

```python
agent.tools.tools_for_profile(agent.tool_profile)
```

因此 `readonly` profile 不会展示 `bash`、`edit_file`、`write_file` 等写入或执行能力。

## `/clear`

`/clear` 由 `GagentRuntime.clear_session()` 执行，不在 CLI 内直接改字段。

行为：

```text
create new SessionState
messages = [current system message]
session_id = new id
SessionEventBus = new <session_id>.events.jsonl
current task/run fields cleared
tool_policy_checker reset
emit session_started(source=slash_command)
save session JSON
```

保留不变：

- provider
- config
- tools
- workspace
- system prompt
- run store root

重置 `ToolPolicyChecker` 是必要的，因为它持有 `fresh_reads` 和 `recent_mutations` 这类 session 内策略状态，不能泄漏到新 session。

## 当前取舍

本阶段不实现：

- `/compact`
- `/resume` 的 REPL 版
- `/model`
- `/history`
- slash command 补全 UI
- skill slash command
- TUI command bridge

这些能力都可以基于当前 registry 和 handler 继续扩展。尤其 `/compact` 应该等 Context Compact 阶段提供 `runtime.compact_history()` 后再挂载。

## 测试覆盖

新增测试覆盖：

- command registry 支持 alias 和 suggestion。
- `/help` 包含当前命令。
- `/status` 输出 session/model/tool profile/message 数。
- `/tools` 遵守当前 tool profile。
- `/clear` 创建新 session，并重置 messages/todos/run state/tool policy state。
- `/quit` 映射到退出。
- 未知 slash command 不调用 provider。
