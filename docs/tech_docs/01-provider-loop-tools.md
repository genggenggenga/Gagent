# Harness 1 技术设计：Provider 抽象 + Agent Loop + Tool Use

## 背景与目标

Harness 1 的目标是打通 Gagent 的最小可运行闭环：模型可以接收用户请求、决定是否调用工具、执行工具、把工具结果回填给模型，并最终输出回答。

这一阶段不是追求完整 agent 产品能力，而是建立后续所有能力都会依赖的三条主线：

- Provider 抽象：屏蔽不同 LLM provider 的调用差异。
- Turn-level Engine：用明确的状态机推进一次用户请求。
- Tool Use：把文件、搜索、shell 等动作变成受控工具边界。

## 总体架构

```text
CLI
  -> resolve_runtime_config()
  -> LiteLLMProvider
  -> GagentRuntime
      -> Engine
      -> ToolRegistry
      -> SessionEventBus / RunStore / TaskState
```

核心职责划分：

- `gagent/providers/*`：负责模型调用和响应归一。
- `gagent/core/runtime.py`：持有 provider、tools、messages、config、观测状态。
- `gagent/core/engine.py`：负责一次 turn 的模型/工具控制流。
- `gagent/tools/*`：定义工具协议、工具注册表和内置工具实现。
- `gagent/core/session_events.py` / `run_store.py` / `task_state.py`：记录运行证据。

## Provider 抽象

Provider 的目标是让 Engine 不关心具体模型 SDK。当前通过 `LiteLLMProvider` 统一接入模型。

### Provider 输入

Provider 的统一入口是：

```python
complete(
    messages: list[Message],
    tools: list[ToolSchema] | None = None,
    *,
    stream: bool = True,
    on_text: TextSink | None = None,
) -> ChatCompletionResult
```

参数含义：

- `messages`：OpenAI-compatible message 列表，由 Engine/Runtime 维护。
- `tools`：当前 tool profile 下可见工具的 schema 列表。
- `stream`：是否启用流式输出。
- `on_text`：流式文本回调，CLI 用它实时打印模型文本。

`LiteLLMProvider` 会把这些参数转换为 LiteLLM 的 `completion()` 参数：

```python
kwargs = {
    "model": self.model,
    "messages": messages,
    "stream": stream,
    "temperature": self.temperature,
    "timeout": self.timeout,
}
```

当存在工具时，额外传入：

```python
kwargs["tools"] = tools
kwargs["tool_choice"] = "auto"
```

这表示是否调用工具由模型自行决定。Engine 不预判工具调用，只消费 Provider 返回的归一化 `stop_reason` 和 `tool_calls`。

### Provider 输出

Provider 对 Engine 返回 `ChatCompletionResult`：

```python
ChatCompletionResult(
    text: str,
    tool_calls: tuple[ToolCall, ...],
    usage: ProviderUsage | None,
    stop_reason: str,
    raw_stop_reason: str,
)
```

相关类型位于 `gagent/providers/types.py`：

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
```

Engine 只根据 `stop_reason` 进行状态迁移：

- `tool_calls`：执行工具并继续循环。
- `stop` / `unknown`：完成当前 turn。
- `length` 或其他原因：停止并标记为未完整完成。

### LiteLLM 接入

`LiteLLMProvider` 的职责是把 LiteLLM 的响应对象、流式 chunk、usage 和 finish reason 统一成 Gagent 内部类型。

支持的配置：

- `model`：LiteLLM 模型名，例如 `deepseek/deepseek-chat`、`openai/gpt-4o-mini`。
- `api_base`：可选 OpenAI-compatible endpoint。
- `api_key`：可选 provider key。
- `temperature`：默认 `0.2`。
- `timeout`：默认 `300` 秒。

这些配置来自 `.env` / CLI 解析后的 `AgentConfig`，Provider 层不关心配置文件来源。

### 流式输出设计

当 `stream=True` 时，`LiteLLMProvider._streaming()` 逐个消费 LiteLLM chunk：

```text
litellm.completion(stream=True)
  -> chunk.choices[0].delta.content
      -> 追加到 full_text
      -> 调用 on_text(content)
  -> chunk.choices[0].delta.tool_calls
      -> 按 index 聚合 tool call id/name/arguments
  -> chunk.choices[0].finish_reason
      -> 记录 raw_stop_reason
```

流式文本处理：

- 每个 `delta.content` 会立即通过 `on_text` 交给 CLI。
- Provider 仍会累积完整 `full_text`，最终放入 `ChatCompletionResult.text`。
- Engine 不直接处理 token delta，只处理最终 completion result。

流式 tool call 处理：

- OpenAI-compatible streaming 中，tool call 的 `name` 和 `arguments` 可能被拆成多个 delta。
- Gagent 按 `tool_delta.index` 聚合同一个 tool call。
- `function.name` 和 `function.arguments` 都以字符串增量方式拼接。
- 流结束后再转换为内部 `ToolCall`。

简化形态：

```python
tool_calls_by_index[index] = {
    "id": "...",
    "function": {
        "name": "read_file",
        "arguments": "{\"path\":\"README.md\"}",
    },
}
```

最终解析为：

```python
ToolCall(
    id="...",
    name="read_file",
    arguments={"path": "README.md"},
)
```

如果 `arguments` 不是合法 JSON，当前会 fallback 为 `{}`。这是保守策略，避免 Provider 层抛异常中断 Engine；后续可在 ToolPolicy/Permission 层返回更清晰的参数错误。

### 非流式输出设计

当 `stream=False` 时，Provider 直接读取：

- `response.choices[0].message.content`
- `response.choices[0].message.tool_calls`
- `response.choices[0].finish_reason`
- `response.usage`

如果提供了 `on_text`，非流式模式会一次性回调完整文本。

非流式 usage 直接来自 provider response：

```text
prompt_tokens -> input_tokens
completion_tokens -> output_tokens
completion_cost(response) -> cost
```

### Usage 与成本统计

Provider 维护累计 usage：

```python
self.total_input_tokens
self.total_output_tokens
self.total_cost
```

非流式模式优先使用 provider 返回的 `response.usage`。

流式模式通常没有完整 usage，因此当前用 LiteLLM 的：

- `token_counter(model=self.model, messages=messages)`
- `token_counter(model=self.model, text=output_text)`
- `completion_cost(model=..., prompt_tokens=..., completion_tokens=...)`

做 best-effort 估算。如果 token/cost 估算失败，则返回 `None`，Engine 仍可继续工作。

### Stop Reason 归一

Provider 层把 provider-specific finish reason 归一成内部 `StopReason`：

```text
has_tool_calls=True              -> tool_calls
stop / end_turn                  -> stop
tool_calls / function_call       -> tool_calls
length / max_tokens              -> length
content_filter / safety          -> content_filter
error                            -> error
other                            -> unknown
```

Engine 因此不依赖 LiteLLM/OpenAI/Anthropic 的原始 finish reason 命名。

## Agent Loop

一次 turn 的主流程：

```text
start_task()
  -> append user message
  -> provider.complete(messages, tool_schemas)
      -> stop_reason == tool_calls
          -> append assistant tool call message
          -> run tool
          -> append tool result message
          -> continue
      -> stop_reason == stop
          -> append assistant final message
          -> write report
          -> return result
```

设计原则：

- Runtime 拥有状态和依赖。
- Engine 只推进 turn-level 控制流。
- Provider 只负责模型响应归一。
- Tool 是所有外部动作的边界。

## Tool Use 设计

基础协议位于 `gagent/tools/base.py`：

### Tool 基础类型

`RegisteredTool` 是模型可见工具的注册单元：

```python
@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    runner: Callable[[dict[str, Any], ToolExecutionContext], ToolResult | str]
    category: Literal["read", "write", "execute"]
    risk_level: Literal["low", "medium", "high"] = "low"
```

字段说明：

- `name`：模型看到的工具名，也是 tool call 中的 function name。
- `description`：给模型看的工具说明，影响模型何时选择该工具。
- `parameters`：JSON Schema object，描述工具参数。
- `runner`：实际执行函数。
- `category`：工具类别，用于 profile、permission 和 prompt 指导。
- `risk_level`：风险等级，用于后续权限和策略。

派生属性：

- `read_only`：`category == "read"`。
- `risky`：`risk_level == "high"`。

### Tool Schema

Gagent 使用 OpenAI-compatible function tool schema。`RegisteredTool.to_schema()` 输出：

```python
{
    "type": "function",
    "function": {
        "name": self.name,
        "description": self.description,
        "parameters": self.parameters,
    },
}
```

这个 schema 会通过 Provider 传给 LiteLLM：

```python
runtime.tool_schemas()
  -> ToolRegistry.schemas_for_profile(profile)
  -> [tool.to_schema(), ...]
  -> LiteLLMProvider.complete(..., tools=schemas)
  -> litellm.completion(tools=schemas, tool_choice="auto")
```

参数 schema 约定：

- 顶层必须是 JSON Schema `object`。
- `properties` 描述每个参数。
- `required` 描述必填参数。
- 尽量在 `description` 中写清路径相对 workspace、是否支持 glob/regex、是否会修改文件。

示意：

```python
parameters = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path relative to the workspace.",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of lines or matches to return.",
        },
    },
    "required": ["path"],
}
```

Tool schema 是模型调用工具的契约，不只是校验信息。它同时承担三件事：

- 让模型知道有哪些工具可用。
- 让模型知道每个工具需要什么参数。
- 约束模型尽量生成可解析的 JSON arguments。

当前 Gagent 不在本地做完整 JSON Schema validation。工具 runner 会读取参数并做必要检查；无效参数会返回 `ToolResult(is_error=True)`。后续可以在 ToolRegistry 执行前补统一 schema validation。

### ToolRegistry

`ToolRegistry` 是工具 allowlist 和 schema 出口：

```python
class ToolRegistry:
    def get(name: str) -> RegisteredTool | None
    def names() -> list[str]
    def tools_for_profile(profile: ToolProfile) -> list[RegisteredTool]
    def schemas_for_profile(profile: ToolProfile) -> list[dict[str, Any]]
    def execute(name, args, context, profile) -> ToolResult
```

设计要点：

- 只有注册过的工具能被执行。
- 只有当前 profile 允许的工具会暴露 schema。
- 即使模型伪造隐藏工具名，`execute()` 也会再次检查 profile。
- 未知工具返回结构化错误，不抛出到 Engine。

### ToolProfile

`ToolProfile` 是工具集合视图：

```python
@dataclass(frozen=True)
class ToolProfile:
    name: str
    allowed_tools: frozenset[str]
```

当前 profile：

- `default`：全部工具。
- `readonly`：所有 `category=read` 的工具。
- `no_shell`：除 `bash` 外的工具。

profile 同时影响两层：

- schema 暴露层：模型只能看到 profile 允许的工具。
- 执行层：即使模型提交隐藏工具名，也会被拒绝。

### ToolExecutionContext

`ToolExecutionContext` 是 runner 的运行上下文：

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    cwd: Path
    workspace: WorkspaceContext | None = None
    sandbox_runner: Any = None
```

关键方法：

```python
resolve_path(raw_path: str) -> Path
relative_path(path: Path) -> str
```

Harness 1 初始阶段只基于 `cwd` 做路径边界；Harness 2 后接入 `WorkspaceContext`，路径边界升级为 repo root。

`sandbox_runner` 在 Harness 3 后给 `bash` 使用，用于把 shell 执行接入 sandbox backend。

### ToolResult

工具统一返回：

```python
@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] | None = None
```

约定：

- `content` 会作为 tool message 回填给模型。
- `is_error=True` 表示工具调用失败，但不会中断 agent loop。
- `metadata` 给 Runtime Events、policy、consumer 使用，不一定回填给模型。

`RegisteredTool.execute()` 会捕获 runner 异常，并转换成：

```python
ToolResult(
    content=f"error: tool {name} failed: {exc}",
    is_error=True,
)
```

这样 Engine 不需要为每个工具写异常处理。

### 内置工具 Schema 摘要

| 工具 | 类别 | 风险 | 关键参数 | 输出约定 |
|------|------|------|----------|----------|
| `list_dir` | `read` | `low` | `path` 默认 `.`；`limit` 默认 `200` | 目录项列表，目录以 `/` 结尾 |
| `glob` | `read` | `low` | `pattern` 必填；`limit` 默认 `200` | workspace-relative 文件路径列表 |
| `grep` | `read` | `low` | `pattern` 必填；`path` 默认 `.`；`include` 可选；`literal` 默认 `false`；`limit` 默认 `100` | `path:line:content` 命中行 |
| `todo_write` | `read` | `low` | `todos` 必填，元素包含 `content` 和 `status` | 当前任务进度列表，metadata 记录 todos 和 counts |
| `read_file` | `read` | `low` | `path` 必填；`start` 默认 `1`；`end` 默认 `200` | 带行号的文本片段 |
| `edit_file` | `write` | `medium` | `path`、`old_text`、`new_text` 必填 | 替换结果和 byte delta，metadata 记录 path |
| `write_file` | `write` | `medium` | `path`、`content` 必填 | 写入 byte 数，metadata 记录 path |
| `bash` | `execute` | `high` | `command` 必填；`timeout` 默认 `120` | `exit_code/stdout/stderr` 结构化文本 |

几点约束：

- `glob.pattern` 不允许绝对路径或 `..` 越界。
- `grep` 优先使用 `rg -n --smart-case`，无 `rg` 时 fallback 到 Python 搜索。
- `grep.literal=true` 时使用字面量搜索；默认按 regex 搜索。
- `todo_write` 只更新运行内任务进度，不修改 workspace 文件，最多允许一个 `in_progress`。
- `read_file` 使用 1-based 行号，`end` 为闭区间。
- `edit_file` 要求 `old_text` 在文件中恰好出现一次。
- `bash` 会先拦截明显危险命令片段，例如 `sudo `、`rm -rf /`、`shutdown`。

内置工具：

- `list_dir`：列目录。
- `glob`：按 glob 查找文件。
- `grep`：搜索文件内容，默认 regex，支持 literal 和 include。
- `todo_write`：更新当前任务进度列表。
- `read_file`：按行读取文件。
- `read_file`：按行读取文件。
- `edit_file`：唯一文本片段替换。
- `write_file`：写文件。
- `bash`：执行 shell 并结构化返回 `exit_code/stdout/stderr`。

### Tool Call 到 Tool Message

模型请求工具时，Provider 返回内部 `ToolCall`：

```python
ToolCall(
    id="call_xxx",
    name="grep",
    arguments={"pattern": "class ToolRegistry", "path": "gagent"},
)
```

Engine 执行后会把结果转成 tool message：

```python
{
    "role": "tool",
    "tool_call_id": "call_xxx",
    "content": result.content,
}
```

然后继续调用模型。模型看到的是工具输出文本，而 Runtime/Trace 额外保留 `is_error` 和 `metadata`。

## 观测闭环

Harness 1 同时引入最小观测闭环：

```text
.gagent/sessions/<session_id>.events.jsonl
.gagent/runs/<run_id>/task_state.json
.gagent/runs/<run_id>/trace.jsonl
.gagent/runs/<run_id>/report.json
```

职责：

- session timeline：记录整个 CLI session 中的粗粒度事件。
- run trace：记录单次任务的细粒度诊断事件。
- task state：记录当前 run 的状态快照。
- report：记录 run 完成后的摘要。

## 当前取舍

- 不做 session resume，只先写运行证据。
- 不做完整 permission/sandbox，只先通过 tool profile 控制模型可见工具。
- 文件边界最初基于 `cwd`，后续由 `WorkspaceContext` 替代。
- `grep` 对模型暴露为 coding agent 习惯工具名，底层优先 `rg`，无 `rg` 时 fallback 到 Python。

## 后续演进

- Workspace 上下文接入后，工具路径解析应基于 repo root 边界。
- Permission / Sandbox 阶段进一步约束写入和 shell。
- Hooks / Runtime Events 阶段统一事件发射，减少 Engine 中观测逻辑。
