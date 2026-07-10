# Gagent 子项目约定

工作区级文档见上级 `../AGENTS.md`（工作区结构、vibe coding 工作流、harness 注册表、全局约定）。

## 工具链
- 包管理：**uv**（`uv sync` / `uv add <pkg>` / `uv run gagent`）
- Python：**>=3.12**
- 布局：flat（`gagent/` 包在仓库根）

## 常用命令
- 安装/同步依赖（含 dev）：`uv sync --extra dev`
- 运行 CLI：`uv run gagent` 或 `uv run python -m gagent`
- 测试：`uv run pytest`
- 代码检查：`uv run ruff check .`

## 实现约定
- 每个 harness 新增依赖用 `uv add` 显式加入，不临时 import。
- 模块按 harness 维度组织；公共能力放 `gagent/` 根下。
- 当前目录结构是阶段性约定，不是最终定稿；随着 agent 能力逐步搭建，可以基于真实实现需要调整模块边界和文件命名。
- 参考 `../reference/` 时只读对照，不直接拷贝整文件；提炼设计后在本项目内重写。
- 新 harness 完成后，回填 `../AGENTS.md` 的 harness 注册表。
