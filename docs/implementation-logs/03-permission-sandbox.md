# Harness 3：Permission / Sandbox

日期：2026-07-13

## 实现范围

- 新增工具策略层：
  - `gagent/core/tool_policy.py`
  - `ToolPolicyChecker` 负责判断工具是否“用对”。
  - 覆盖先读后改、bash 搜索纠偏、重复高风险写调用拦截。
- 新增权限决策层：
  - `gagent/core/permissions.py`
  - `PermissionChecker` 负责判断工具当前是否允许执行。
  - 支持 `approval_policy=auto|never`。
  - 支持 tool profile 拦截和 workspace 路径越界拦截。
- 新增 shell sandbox runner：
  - `gagent/features/sandbox.py`
  - `SandboxConfig` 支持 `off|best_effort|required`。
  - Linux 可通过 `bubblewrap` 后端执行 bash。
  - macOS / 无可用后端时，`best_effort` 降级直跑并发事件，`required` fail closed。
- Runtime 接入：
  - `GagentRuntime.run_tool()` 变为统一工具执行边界。
  - 执行顺序为：`ToolPolicyChecker` -> `PermissionChecker` -> tool runner。
  - `tool_policy_decision`、`permission_decision`、`sandbox_unavailable` 写入 session event 和 run trace。
- bash 工具接入：
  - `bash` 工具优先通过 `ToolExecutionContext.sandbox_runner` 执行。
  - 保留原有危险命令硬拦截和结构化 `exit_code/stdout/stderr` 输出。
- CLI 配置：
  - 新增 `--approval-policy auto|never`。
  - 新增 `--sandbox off|best_effort|required`。
  - 新增 `--sandbox-backend auto|bubblewrap|none`。
- 新增测试：
  - `tests/test_permissions.py`
  - `tests/test_sandbox.py`
  - 扩展 `tests/test_agent_loop.py`
  - 扩展 `tests/test_cli.py`
  - 扩展 `tests/test_prompt.py`

## 参考来源

- 权限链路参考 learn-claude-code `s03_permission/code.py`：
  - 教学版的三段式 pipeline 是 `deny list -> rule match -> approval`。
  - Gagent 保留这个心智模型，但拆成 policy、permission、runner 三层。
- 权限决策参考 pico-v3 `core/permissions.py`：
  - profile 是第一道硬边界。
  - read-only 工具默认允许。
  - 非只读工具受 approval policy 控制。
- 工具策略参考 pico-v3 `core/tool_policy.py`：
  - 修改已有文件前要求 fresh read。
  - shell 中普通搜索/读取类命令应改用专门工具。
  - 策略拒绝不是安全审批，而是引导模型修正工具使用方式。
- sandbox 参考 pico-v3 `features/sandbox/`：
  - Linux 使用 `bubblewrap`。
  - `best_effort` 可降级，`required` 必须 fail closed。
  - sandbox 作为 bash runner 的执行后端，不进入 Engine。

## 当前取舍

- 本阶段不实现交互式 ask approval：
  - 先提供 `approval_policy=auto|never`。
  - `ask` 模式需要 CLI/Engine 支持暂停等待用户输入，放到 Hooks / Runtime Events 阶段后实现更自然。
- 本阶段不实现 plan mode：
  - 预留了 policy / permission 分层。
  - 后续进入 Plan / Todo 阶段再加“只能写 plan artifact”等规则。
- macOS 默认不提供强 sandbox：
  - `backend=auto` 在没有 `bubblewrap` 时视为 unavailable。
  - `best_effort` 降级直跑并记录 `sandbox_unavailable`。
  - `required` 直接拒绝，避免给用户错误安全感。
- `ToolPolicyChecker` 维护轻量运行内状态：
  - 成功 `read_file` 后记录 fresh read 路径。
  - 成功写工具后记录 mutation key，用于阻止重复高风险写调用。
  - 当前还不做文件 freshness hash，后续 Memory / Session 阶段再增强。

## 验证记录

- `/Users/bytedance/.local/bin/uv run pytest -q`：34 个测试全部通过。
- `/Users/bytedance/.local/bin/uv run ruff check`：通过。
