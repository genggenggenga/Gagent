# Gagent Harness 设计目录

Gagent 可实现的 harness 清单，按 learn-claude-code 六阶段递进组织，并映射到 `reference/` 中的生产级实现。选型后到 `AGENTS.md`（工作区根）的「Harness 注册表」登记实现状态。

## 参考路径缩写

- `lc` = `reference/learn-claude-code/`（教学式 s01–s20，每章一个 `code.py`）
- `pico3` = `reference/pico-v3/`（pico v3 分支纯文件快照，生产级，`core/` 最丰富）
- `picoM` = `reference/pico/`（pico main 分支）
- `any` = `reference/AnyCoder/`（litellm 多 provider + tools/prompts 分包）

## 阶段 1 — 让 agent 能动手

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 1 | **Agent Loop** | 一个循环 + bash = 一个 agent | lc `s01`；pico3 `core/runtime.py` `core/turn_history.py` `core/turn_transitions.py`；any `agent.py` |
| 2 | **Tool Use** | 循环不动，新工具注册进 dispatch map | lc `s02`；pico3 `tools/registry.py` `tools/base.py` `core/tool_executor.py` `tools/schemas.py`；any `tools/{read_file,edit_file,glob_tool,write_file,bash,grep_tool}.py` |
| 3 | **Permission** | 先划边界，再给自由 | lc `s03`；pico3 `core/permissions.py` `core/tool_policy.py` `core/tool_profiles.py` `features/sandbox/`；picoM `security.py` |
| 4 | **Hooks** | 挂在循环上，不写进循环里 | lc `s04`；pico3 `core/before_final_hooks.py` `core/runtime_events.py` `core/runtime_consumers.py`（部分） |

## 阶段 2 — 做复杂任务

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 5 | **TodoWrite** | 先列步骤再动手，完成率翻倍 | lc `s05`；pico3 `core/task_state.py` `core/todo_ledger.py` `tools/todos.py` |
| 6 | **Subagent** | 大任务拆小，干净上下文只带回结果 | lc `s06`；pico3 `tools/agents.py` `core/worker_{manager,execution,runtime,notifications,artifacts}.py` |
| 7 | **Context Compact** | 上下文总会满，便宜先跑贵后跑 | lc `s08`；pico3 `core/compact.py` `core/compact_summary.py` `core/context_{orchestrator,pressure,replacements,retention,sections,usage,budget_summary,handoff}.py`（最丰富） |

## 阶段 3 — 记住和恢复

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 8 | **Memory** | 记住该记的，忘掉该忘的 | lc `s09`；pico3 `features/memory.py` `features/memory_{lint,quarantine}.py` |
| 9 | **System Prompt** | prompt 是组装出来的，不是写死的 | lc `s10`；picoM `prompt_prefix.py`；any `prompts/system.py` |
| 10 | **Error Recovery** | 错误是重试的起点：重试、腾空间、换路子 | lc `s11`；pico3 `core/model_errors.py` `core/model_router.py` `core/completion_governance.py` `core/final_readiness*.py` `core/verification.py` |

## 阶段 4 — 让任务长期运行

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 11 | **Task System** | 大目标拆小任务，排依赖，落盘 | lc `s12`；pico3 `core/task_state.py` `core/run_store.py` `core/session_store.py` |
| 12 | **Background Tasks** | 慢操作丢后台，完成后注入通知 | lc `s13`；pico3 `core/worker_{runtime,notifications}.py` |
| 13 | **Cron Scheduler** | 定时触发，不需要人推 | lc `s14`（pico 无对应，仅 lc） |

## 阶段 5 — 让多个 agent 协作

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 14 | **Agent Teams** | 一个搞不定，组队来：持久队友 + 异步邮箱 | lc `s15`（pico 无） |
| 15 | **Team Protocols** | 队友之间要有固定收发格式 | lc `s16`（pico 无） |
| 16 | **Autonomous Agents** | 队友自己看板认领，自组织 | lc `s17`（pico 无） |
| 17 | **Worktree Isolation** | 各干各的目录，任务-目录按 ID 绑定 | lc `s18`；pico3 `core/workspace.py` |

## 阶段 6 — 接外部能力合体

| # | Harness | 格言 | 参考实现 |
|---|---------|------|----------|
| 18 | **Skill Loading** | 用到时再加载，别全塞 prompt | lc `s07`；pico3 `features/skills.py` `features/skills_{bundled,runtime}.py` |
| 19 | **MCP Plugin** | 能力不够？外部工具接进同一工具池 | lc `s19`（pico 无） |
| 20 | **Comprehensive** | 机制很多，循环一个 | lc `s20`（整合验收） |

## 横切能力（lc 不作为单独 stage，但 pico/AnyCoder 有生产实现）

| Harness | 作用 | 参考实现 |
|---------|------|----------|
| **Provider 抽象** | 多 LLM 接入（OpenAI/Anthropic/Ollama 兼容） | any `llm.py`（litellm）；pico3 `providers/{base,clients,errors,runtime}.py` |
| **Session 持久化 / Checkpoint** | 会话 resume/fork、运行快照 | pico3 `core/session_store.py` `core/session_{events,lifecycle}.py` `core/run_store.py` `core/runtime_checkpoints.py`；picoM `checkpoint.py` `session_store.py` |
| **Workspace 上下文** | 工作目录/项目根/路径解析 | pico3 `core/workspace.py`；picoM `workspace.py` |
| **TUI / CLI** | 终端交互界面 | pico3 `tui/{app,main,widgets}.py` `cli.py`；any `cli.py` |
| **Slash 命令** | `/compact` `/clear` 等用户指令 | pico3 `commands/slash.py` |
| **Evaluation / Benchmark** | agent 质量评测 | pico3 `evaluation/{harnessbench,metrics,context_cost,run_evidence,dream_quality,memory_agent_eval}.py` |
| **多模态 (Vision/Media)** | 图片输入/截图 | pico3 `core/{media,media_history,vision}.py` |

## 实现顺序建议

learn-claude-code 的 s01→s20 是教学递进，但做产品要更早打底座。建议 Gagent 按此顺序：

1. **Provider 抽象 + Agent Loop + Tool Use**（最小能跑的 agent，接一个 LLM 就能对话+用工具）
2. **Workspace 上下文 + System Prompt**（落地到真实项目目录）
3. **Permission**（给 bash/写文件加边界，安全）
4. **TodoWrite + Context Compact**（能做稍长任务）
5. **Session 持久化/Checkpoint**（能 resume）
6. **Subagent + Error Recovery + Hooks**
7. 之后按需：Memory / Skill / Background / Task System / 团队 / MCP / TUI / Eval

横切的 **Provider 抽象**放最前——它决定整个 LLM 调用层形状，后补很痛。
