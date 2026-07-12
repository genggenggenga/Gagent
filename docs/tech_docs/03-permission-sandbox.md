# Harness 3 技术设计：Permission / Sandbox

## 背景与目标

Harness 3 的目标是给工具执行加上清晰边界：模型可以继续使用工具，但工具调用必须先经过策略纠偏、权限判断和必要的 shell sandbox。

这一阶段重点不是做完整交互审批，而是建立可测试、可演进的执行管线。

## 总体执行链路

```text
ToolCall
  -> ToolPolicyChecker
  -> PermissionChecker
  -> ToolRegistry.execute()
      -> bash
          -> SandboxRunner.run()
```

三层职责：

- ToolPolicy：判断工具是否“用对”。
- Permission：判断工具当前是否“允许执行”。
- Sandbox：决定 bash 命令“如何执行”。

## ToolPolicyChecker

实现位于 `gagent/core/tool_policy.py`。

职责是纠正模型工具使用方式，而不是安全审批。

当前规则：

### 修改前必须读取

对于：

- `edit_file`
- 覆盖已有文件的 `write_file`

必须先成功调用 `read_file` 读取目标文件。

这样可以减少模型在不了解文件内容时直接覆盖或替换。

### bash 搜索纠偏

如果 `bash` 命令在主命令位置使用：

- `cat`
- `less`
- `head`
- `tail`
- `grep`
- `rg`
- `find`
- `ls`

会被拒绝，并提示模型使用专门工具：

- `grep`
- `glob`
- `list_dir`
- `read_file`

管道后的 `head/tail/grep` 可在后续细化，目前重点拦截普通 workspace 搜索/读取。

### 重复高风险写调用拦截

成功写工具后记录 mutation key。如果模型重复执行完全相同的写调用，会被拒绝，避免陷入重复覆盖。

## PermissionChecker

实现位于 `gagent/core/permissions.py`。

职责是判断工具是否允许执行。

输入包括：

- `RegisteredTool`
- 工具参数
- `ToolExecutionContext`
- 当前 `ToolProfile`

当前规则：

### Tool Profile 边界

如果当前 profile 不允许该工具，直接拒绝。

例如：

- `readonly` 不允许写工具和 `bash`
- `no_shell` 不允许 `bash`

### Workspace 路径边界

读写类工具的路径必须通过：

```python
context.resolve_path(path)
```

无法解析或越过 workspace 边界时拒绝。

### Approval Policy

当前支持：

- `auto`：允许非只读工具执行。
- `never`：拒绝写工具和执行工具。

暂不支持 `ask`，因为交互审批需要 CLI/Engine 支持暂停等待用户输入。

## SandboxRunner

实现位于 `gagent/features/sandbox.py`。

Sandbox 是 `bash` 的执行后端，不是普通 hook。

配置：

```python
SandboxConfig(
    mode="off" | "best_effort" | "required",
    backend="auto" | "bubblewrap" | "none",
    workspace_write=True,
    excluded_commands=(),
)
```

### Linux

Linux 上优先使用 `bubblewrap` 后端。

设计语义：

- `off`：直接执行。
- `best_effort`：有 `bwrap` 则使用；没有则直跑并发出 `sandbox_unavailable`。
- `required`：必须有 `bwrap`；没有则 fail closed。

`bubblewrap` 执行时会把 workspace bind 到沙盒环境中，并以 `/bin/sh -lc` 运行命令。

### macOS

macOS 当前不伪装强 sandbox。

原因：

- 无原生 `bubblewrap`。
- `sandbox-exec` / Seatbelt 兼容性和可维护性较差。
- 开发命令常依赖 `$HOME`、cache、toolchain、临时目录。

因此当前行为：

- `off`：直接执行。
- `best_effort`：后端不可用时直跑并记录事件。
- `required`：后端不可用时拒绝执行。

这样避免给用户错误的安全感。

## Runtime 接入

Harness 3 后，`GagentRuntime.run_tool()` 成为统一工具执行边界。

执行顺序：

```text
tool lookup
  -> ToolPolicyChecker.check()
  -> PermissionChecker.check()
  -> tools.execute()
  -> ToolPolicyChecker.record_result()
```

拒绝时返回结构化 tool result：

```python
{
    "is_error": True,
    "content": "...",
    "metadata": {"tool_error_code": "..."},
}
```

## CLI 参数

新增：

```bash
--approval-policy auto|never
--sandbox off|best_effort|required
--sandbox-backend auto|bubblewrap|none
```

默认值保持原行为：

```text
approval_policy=auto
sandbox=off
sandbox_backend=auto
```

## 事件

权限和策略决策会写入运行事件：

- `tool_policy_decision`
- `permission_decision`
- `sandbox_unavailable`

这些事件可进入 session timeline 和 run trace，便于复盘为什么工具没有执行。

## 当前取舍

- 不做交互式 `ask` approval。
- 不做 plan mode 的特殊写入规则。
- 不做强 macOS sandbox。
- `ToolPolicyChecker` 的 fresh read 只在当前 runtime 内存中维护，暂不做文件 hash freshness。

## 后续演进

- Hooks 阶段将 policy/permission 迁入 mandatory hooks。
- Session 阶段可持久化 fresh read / mutation 状态。
- Plan/Todo 阶段可增加“只允许写 plan artifact”的规则。
- 未来可探索 macOS seatbelt 实验后端，但不应作为默认安全承诺。
