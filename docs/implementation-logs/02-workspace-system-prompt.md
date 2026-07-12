# Harness 2：Workspace 上下文 + System Prompt

日期：2026-07-12

## 实现范围

- 新增 Workspace 上下文：
  - `gagent/core/workspace.py`
  - `WorkspaceContext` 负责发现 `cwd`、`repo_root`、git 分支、默认分支、git status、recent commits 和白名单项目文档摘要。
  - `ProjectDocument` 用于保存 `AGENTS.md`、`README.md`、`pyproject.toml`、`package.json` 等项目文档片段。
- 升级 System Prompt 组装：
  - `gagent/core/prompt.py`
  - `build_system_prompt()` 从真实 workspace、tool registry 和 tool profile 组装 prompt。
  - `SystemPrompt` 保存 prompt 文本、hash、workspace fingerprint、tool signature 和构建时间。
- Runtime 接入：
  - `GagentRuntime` 启动时构建 `WorkspaceContext`。
  - Runtime 持有 `system_prompt`，并把 prompt 文本写入初始 system message。
  - `session_started` 事件记录 `workspace_root`、`cwd` 和 `system_prompt_hash`。
- Tool Context 接入：
  - `ToolExecutionContext` 新增可选 `workspace`。
  - 文件工具统一通过 `context.resolve_path()` 解析路径。
  - 从 git 子目录启动时，文件工具允许访问 repo root 内路径，但仍拒绝越界。
- 新增测试：
  - `tests/test_workspace.py`
  - `tests/test_prompt.py`
  - 扩展 `tests/test_agent_loop.py`
  - 扩展 `tests/test_tools.py`

## 参考来源

- Workspace 主要参考 pico / pico-v3 的 `workspace.py`：
  - 不预加载整个仓库，只给模型一份便宜、稳定的“仓库第一印象”。
  - 收集 git 事实和少量白名单项目文档。
  - 使用 fingerprint 表示 workspace 上下文是否变化。
- System Prompt 主要参考 pico 的 `prompt_prefix.py`：
  - prompt 由稳定 section 组装。
  - 为 workspace 和工具集计算签名，给后续 prompt cache / session resume 留接口。
- Prompt 动态组装参考 learn-claude-code 的 `s10_system_prompt/code.py`：
  - prompt 不是硬编码字符串，而是由 runtime context 决定。
  - 根据真实状态决定哪些 section 进入 prompt。
- Coding agent 行为规则参考 AnyCoder 的 `prompts/system.py`：
  - 明确工具使用习惯、安全边界、先读后改、少量解释、精确修改等行为约束。

## 当前取舍

- Workspace 边界采用 `repo_root`：
  - git 仓库中用 `git rev-parse --show-toplevel` 发现根目录。
  - 非 git 目录 fallback 到启动 `cwd`。
  - `cwd` 仍作为相对路径解析起点和 bash 执行目录。
- Project docs 只读取白名单文件：
  - `AGENTS.md`
  - `README.md`
  - `pyproject.toml`
  - `package.json`
  - 每个文档片段最多保留 1200 字符，避免 prompt 膨胀。
- Prompt 中只放工具使用指导，不重复注入完整 tool JSON schema：
  - Provider 调用仍通过 tool schema 暴露工具参数。
  - System Prompt 只负责告诉模型何时用什么工具。
- 本阶段只保留 prompt hash / workspace fingerprint / tool signature：
  - 暂不实现 prompt cache。
  - 后续 Session / Compact 阶段再利用这些签名做缓存和恢复判断。
- `ToolExecutionContext` 保留 `cwd` 字段并新增 `workspace`：
  - 兼容现有测试和调用方。
  - 新工具优先使用 `context.resolve_path()`。

## 验证记录

- `/Users/bytedance/.local/bin/uv run pytest -q`：25 个测试全部通过。
- `/Users/bytedance/.local/bin/uv run ruff check`：通过。
