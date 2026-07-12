# Harness 2 技术设计：Workspace 上下文 + System Prompt

## 背景与目标

Harness 2 的目标是让 Gagent 真正理解“它正在哪个项目里工作”，并把项目事实稳定地注入给模型。

这一阶段解决两个问题：

- Workspace：从裸 `cwd` 升级为结构化项目上下文。
- System Prompt：从硬编码字符串升级为由 runtime context 组装的 prompt。

## 设计原则

- 不把整个仓库塞进 prompt。
- 只给模型一份便宜、稳定、可裁剪的“仓库第一印象”。
- prompt 由 section 组装，并带 fingerprint/signature，方便后续缓存和恢复。
- 工具路径边界优先使用 workspace 统一解析。

## WorkspaceContext

核心实现位于 `gagent/core/workspace.py`。

主要数据结构：

```python
@dataclass(frozen=True)
class WorkspaceContext:
    cwd: Path
    repo_root: Path
    branch: str
    default_branch: str
    git_status: str
    recent_commits: tuple[str, ...]
    project_docs: tuple[ProjectDocument, ...]
```

`WorkspaceContext.build(cwd)` 负责发现当前项目事实：

- `repo_root`：优先使用 `git rev-parse --show-toplevel`。
- 非 git 目录：fallback 到启动 `cwd`。
- `branch`：当前 git branch。
- `default_branch`：默认分支，无法识别时为 `main`。
- `git_status`：短格式 status。
- `recent_commits`：最近若干 commit。
- `project_docs`：白名单项目文档摘要。

## Project Documents

当前只读取白名单文件：

- `AGENTS.md`
- `README.md`
- `pyproject.toml`
- `package.json`

每个文件最多注入 1200 字符，避免 prompt 膨胀。

读取位置包括：

- `repo_root`
- 当前启动 `cwd`

这样既支持从仓库根启动，也支持从子目录启动时读取局部约定。

## 路径边界

`WorkspaceContext.resolve_path(raw_path)` 负责统一路径解析。

规则：

```text
raw_path 相对 cwd 解析
  -> resolve()
  -> 必须在 repo_root 内
```

效果：

- 从子目录启动时，可以访问 repo root 内的文件。
- 不能越过 repo root。
- 非 git 目录时，repo root 等于 cwd。

`ToolExecutionContext` 新增可选 `workspace`：

```python
ToolExecutionContext(
    cwd=config.cwd,
    workspace=workspace,
)
```

新工具应优先使用：

```python
context.resolve_path(path)
```

## SystemPrompt

核心实现位于 `gagent/core/prompt.py`。

`build_system_prompt()` 输入：

```python
build_system_prompt(
    workspace=workspace,
    tools=tool_registry,
    profile=tool_profile,
)
```

输出：

```python
@dataclass(frozen=True)
class SystemPrompt:
    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    built_at: str
```

system prompt 包含：

- agent identity
- operating rules
- tool guidance
- workspace facts
- project docs snippets

Prompt 中不重复注入完整 tool JSON schema，因为 provider 调用会单独传 schema。Prompt 只告诉模型“什么时候应该使用什么工具”。

## Runtime 接入

Runtime 初始化流程：

```text
WorkspaceContext.build(config.cwd)
  -> build_system_prompt(workspace, tools, profile)
  -> system_message(system_prompt.text)
  -> runtime.messages[0]
```

也就是说 workspace 不是单独作为 provider 参数传入，而是被渲染进 system message，然后随 `runtime.messages` 传给 LLM。

## Fingerprint 与 Signature

`workspace.fingerprint()` 用于表示 workspace facts 是否变化。

`tool_signature()` 用于表示当前 tool profile 下工具集合是否变化。

当前阶段只计算并保存这些值，暂不做 prompt cache。后续可用于：

- session resume
- prompt cache
- context compact
- runtime identity mismatch 检测

## 当前取舍

- 不做深度仓库索引，只做轻量 workspace facts。
- 不读取任意文档，只读取白名单文件。
- 不做 prompt cache，只保留 hash/signature。
- 保留 `cwd` 作为 bash 执行目录，`repo_root` 作为 workspace 边界。

## 后续演进

- Session 持久化阶段可保存 workspace fingerprint。
- Compact 阶段可根据 fingerprint 判断 prompt prefix 是否可复用。
- Skills 阶段可把领域说明按需注入，而不是放入基础 system prompt。
