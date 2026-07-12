# Gagent 实现记录

本文是实现记录索引。每个阶段单独放在 `docs/implementation-logs/` 下，记录该阶段的实现范围、设计取舍、参考来源和验证结果。

这些记录不是最终设计文档，而是帮助后续回看“当时为什么这样做”的工程日志。目录和模块边界仍然可以随着 agent 能力逐步搭建而调整。

## 记录列表

| 阶段 | 日期 | 记录 |
|------|------|------|
| Harness 1：Provider 抽象 + Agent Loop + Tool Use | 2026-07-11 | [01-provider-loop-tools.md](implementation-logs/01-provider-loop-tools.md) |
| Harness 2：Workspace 上下文 + System Prompt | 2026-07-12 | [02-workspace-system-prompt.md](implementation-logs/02-workspace-system-prompt.md) |
| Harness 3：Permission / Sandbox | 2026-07-13 | [03-permission-sandbox.md](implementation-logs/03-permission-sandbox.md) |
| Harness 4：Hooks / Runtime Events | 2026-07-13 | [04-hooks-runtime-events.md](implementation-logs/04-hooks-runtime-events.md) |

## 新增记录约定

- 文件放在 `docs/implementation-logs/`。
- 文件名使用两位阶段序号和短横线描述，例如 `02-workspace-prompt.md`。
- 每份记录至少包含：实现范围、参考来源、当前取舍、验证记录。
