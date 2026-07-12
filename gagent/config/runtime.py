"""Runtime configuration resolution.

CLI arguments are strings and flags. This module turns them into the structured
configuration object consumed by `GagentRuntime`.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from gagent.core.runtime import AgentConfig

DEFAULT_MODEL = "deepseek/deepseek-chat"


def resolve_runtime_config(args: Any) -> AgentConfig:
    cwd = Path(args.cwd).expanduser().resolve()
    load_dotenv(cwd / ".env", override=False)
    load_dotenv(override=False)

    model = args.model or os.environ.get("GAGENT_MODEL") or DEFAULT_MODEL
    api_base = (
        args.api_base
        or os.environ.get("GAGENT_API_BASE")
        or os.environ.get("OPENAI_API_BASE")
    )
    api_key = (
        args.api_key
        or os.environ.get("GAGENT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    return AgentConfig(
        cwd=cwd,
        model=model,
        api_base=api_base,
        api_key=api_key,
        temperature=args.temperature,
        timeout=args.timeout,
        max_steps=args.max_steps,
        stream=not args.no_stream,
        tool_profile=args.tool_profile,
    )
