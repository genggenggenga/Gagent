# Gagent 项目结构约定

本文定义 Gagent 后续按 harness 递进实现时的阶段性目录边界。目标是先给当前实现一个清晰骨架，避免每个 harness 各自散落实现；但目录和接口不是最终定稿，可以随着 agent 能力一点点搭起来，在真实实现中持续调整。

## 设计原则

- **按能力边界组织模块**：Agent Loop、Provider、Tool、Workspace、Prompt、Permission、Session 等分别有清晰归属。
- **公共能力放在 `gagent/` 内**：遵循本项目 flat 布局，`gagent/` 包在仓库根。
- **参考项目只读对照**：参考 `../reference/` 下项目时只提炼设计，不直接拷贝整文件。
- **先轻量再扩展**：MVP 只实现当前 harness 需要的最小接口，后续 harness 再补完整能力。
- **允许演进目录接口**：当前目录结构是对下一阶段开发的最佳假设，不是不可变接口；当实现暴露出更自然的边界时，应及时调整目录、模块名和职责划分。

## 参考项目映射

- `lc`：`../reference/learn-claude-code/`，教学式 s01-s20 拆解。
- `any`：`../reference/AnyCoder/`，重点参考 LiteLLM provider 接入、tools/prompts 分包。
- `picoM`：`../reference/pico/`，重点参考 `pico/workspace.py`、checkpoint、session 等产品化实现。
- `pico3`：`../reference/pico-v3/`，重点参考 `pico/core/` 下更完整的 runtime、workspace、context、task、trace 实现。

## 目标目录结构

```text
gagent/
  __init__.py
  __main__.py
  cli.py

  core/
    agent.py
    messages.py
    runtime.py

  providers/
    base.py
    litellm.py
    types.py

  tools/
    base.py
    registry.py
    builtin/
      bash.py
      read_file.py
      write_file.py

  workspace/
    context.py
    files.py

  prompts/
    system.py
    templates.py

  permissions/
    policy.py
    sandbox.py

  sessions/
    models.py
    store.py

  context/
    budget.py
    compact.py

  errors/
    recovery.py

  tracing/
    events.py
```

说明：上面是当前阶段的目标结构，不要求一次性建空目录，也不表示这些目录接口已经彻底定死。每个 harness 开始时，只创建它真正需要的模块；如果后续实现证明边界不合适，可以小步重构。

## 核心边界

### Provider

Provider 层负责统一 LLM 调用接口，Gagent 优先参考 AnyCoder 的 LiteLLM 接入方式。

`core/` 只依赖 Gagent 自己的 Provider 抽象，不直接依赖 OpenAI、Anthropic 或具体模型 SDK。后续多模型、多 provider、token 统计和错误归一，都收敛在 `gagent/providers/`。

### Agent Loop

Agent Loop 负责一轮或多轮对话的主循环：组装消息、调用 provider、识别 tool call、执行工具、把结果写回消息历史。

Agent Loop 不直接处理具体文件路径、不直接执行 shell、不直接拼大型 system prompt；这些分别交给 Workspace、Tool、Prompt 模块。

### Tool

Tool 层负责把具体能力注册进统一工具池，并返回结构化执行结果。工具不知道 agent loop 的内部状态，只接收明确参数和必要上下文。

工具执行前的安全决策交给 Permission / Sandbox，路径解析交给 Workspace。

### Workspace

Workspace 表示 agent 当前可理解和可操作的项目空间。它不是 Session，也不是 Memory。

MVP 的 Workspace 负责：

- 记录 `cwd` 和 `repo_root`。
- 解析用户或工具传入的相对路径。
- 判断路径是否位于项目边界内。
- 收集少量项目级事实，如 git 分支、git status、README、AGENTS、pyproject 等摘要。
- 为 System Prompt 提供稳定的项目第一印象。

Workspace 参考 pico 的显式 `WorkspaceContext` 思路；AnyCoder 中分散在 prompt 和 tools 里的 `cwd` 处理，不直接照搬为最终结构。

### Prompt

Prompt 层负责组装 system prompt 和可复用模板。Workspace、Permission、Tool Registry 等模块只提供结构化信息，由 Prompt 层决定如何表达给模型。

### Permission / Sandbox

Permission / Sandbox 是工具执行前的 gate。它依赖 Workspace 判断路径边界，依赖 Tool 元数据判断操作类型，避免把安全逻辑散落在每个工具里。

### Session

Session 负责记录会话和运行历史，例如 session id、turns、messages、workspace、provider 配置、tool call 记录。

Session 持久化需要尽早实现，但完整 Checkpoint 不作为 MVP 硬前置。运行快照、fork、后台任务恢复、子 agent 状态恢复等，可以在 Background Task / Task System 阶段补齐。

### Context / Memory / Trace

Context 负责当前模型上下文预算和 compact；Memory 负责长期偏好和项目知识；Trace 负责运行事件和调试证据。三者不要混成一个模块。

## harness 落地顺序和目录关系

| 顺序 | Harness | 主要目录 |
|------|---------|----------|
| 1 | Provider 抽象 + Agent Loop + Tool Use | `providers/` `core/` `tools/` |
| 2 | Workspace 上下文 + System Prompt | `workspace/` `prompts/` |
| 3 | Permission / Sandbox | `permissions/` |
| 4 | Session 持久化 | `sessions/` |
| 5 | Context Compact | `context/` |
| 6 | Error Recovery | `errors/` |
| 7 | Todo / Trace / State | `core/` `tracing/` |
| 8+ | Memory / Hooks / Slash / Skills / MCP / Background / Task / Eval | 按能力新增模块 |

## 当前阶段建议

开始写第一个 harness 时，优先落地：

```text
gagent/core/
gagent/providers/
gagent/tools/
```

接着在第二个 harness 落地：

```text
gagent/workspace/
gagent/prompts/
```

这样既能保证 Provider 参考 AnyCoder 的 LiteLLM 接入，也能把 Workspace 按 pico 的显式上下文模型独立出来，后续 Permission、Session、Context Compact 和 Subagent 都可以复用同一个项目边界。
