"""Compatibility entry points for agent-shaped imports.

The primary runtime lives in `gagent.core.runtime`. The turn-level loop lives in
`gagent.core.engine`, following pico-v3's runtime/engine split.
"""

from gagent.core.engine import AgentRunResult
from gagent.core.runtime import AgentConfig, GagentRuntime

Agent = GagentRuntime

__all__ = ["Agent", "AgentConfig", "AgentRunResult", "GagentRuntime"]
