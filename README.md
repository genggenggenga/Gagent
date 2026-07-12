# Gagent

Gagent is a Python coding agent built harness by harness, referencing the projects under `../reference/`.

See `../AGENTS.md` for the workspace workflow and harness registry. See `AGENTS.md` for this subproject's toolchain and implementation conventions.

## Requirements

- Python >= 3.12
- uv
- A LiteLLM-compatible provider key

Install uv if it is not available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If the current shell cannot find `uv` after installation, use the full path:

```bash
/Users/bytedance/.local/bin/uv --version
```

## Environment Setup

Sync runtime and dev dependencies:

```bash
/Users/bytedance/.local/bin/uv sync --extra dev
```

This creates `.venv/` and installs the project dependencies, including:

- `litellm`
- `python-dotenv`
- `pytest`
- `ruff`

## Provider Configuration

Gagent loads environment variables from the workspace `.env` first, then from the current shell environment.

Create a local `.env` file in the project or target workspace:

```bash
GAGENT_MODEL=deepseek/deepseek-chat
GAGENT_API_KEY=sk-...
GAGENT_API_BASE=https://api.example.com/v1
```

Supported environment variables:

| Variable | Description |
|----------|-------------|
| `GAGENT_MODEL` | LiteLLM model name. Defaults to `deepseek/deepseek-chat`. |
| `GAGENT_API_KEY` | Provider API key. |
| `GAGENT_API_BASE` | Custom provider API base URL. |
| `OPENAI_API_KEY` | Fallback API key for OpenAI-compatible providers. |
| `OPENAI_API_BASE` | Fallback API base for OpenAI-compatible providers. |

CLI arguments override environment variables:

```bash
/Users/bytedance/.local/bin/uv run gagent \
  --model deepseek/deepseek-chat \
  --api-key sk-... \
  --api-base https://api.example.com/v1 \
  "Summarize this project"
```

## Startup

Run one-shot mode:

```bash
/Users/bytedance/.local/bin/uv run gagent "List the files in this project"
```

Run interactive REPL mode:

```bash
/Users/bytedance/.local/bin/uv run gagent
```

Inside the REPL:

```text
gagent> Read README.md
gagent> /exit
```

Run against another workspace:

```bash
/Users/bytedance/.local/bin/uv run gagent --cwd /path/to/repo "Inspect the project structure"
```

List available tools:

```bash
/Users/bytedance/.local/bin/uv run gagent --list-tools
```

Use a tool profile:

```bash
/Users/bytedance/.local/bin/uv run gagent --tool-profile readonly "Read README.md"
/Users/bytedance/.local/bin/uv run gagent --tool-profile no_shell "Update a small file"
```

Current tool profiles:

| Profile | Behavior |
|---------|----------|
| `default` | Exposes all current tools. |
| `readonly` | Exposes only read-only tools. |
| `no_shell` | Hides shell execution while keeping file tools available. |

## Common Commands

```bash
/Users/bytedance/.local/bin/uv run gagent --help
/Users/bytedance/.local/bin/uv run pytest
/Users/bytedance/.local/bin/uv run ruff check .
```

Short forms also work when `uv` is on `PATH`:

```bash
uv sync --extra dev
uv run gagent
uv run pytest
uv run ruff check .
```
