# Gagent 技术设计文档

本文档目录沉淀各 harness 的稳定技术设计。和 `docs/implementation-logs/` 不同，这里关注模块边界、数据流、设计取舍和后续演进，不记录具体实现流水账。

## 文档列表

| 阶段 | 文档 |
|------|------|
| Harness 1：Provider 抽象 + Agent Loop + Tool Use | [01-provider-loop-tools.md](01-provider-loop-tools.md) |
| Harness 2：Workspace 上下文 + System Prompt | [02-workspace-system-prompt.md](02-workspace-system-prompt.md) |
| Harness 3：Permission / Sandbox | [03-permission-sandbox.md](03-permission-sandbox.md) |
| Harness 4：Hooks / Runtime Events | [04-hooks-runtime-events.md](04-hooks-runtime-events.md) |
| Harness 5：TodoWrite / Task Progress State | [05-todowrite-task-progress.md](05-todowrite-task-progress.md) |
| Harness 6：Session 持久化 / Resume | [06-session-persistence-resume.md](06-session-persistence-resume.md) |

## 维护约定

- 每完成一个 harness，新增或更新对应技术设计文档。
- 实现日志记录过程，技术设计文档记录稳定结构。
- 如果后续重构改变模块边界，应同步更新本目录对应文档。
