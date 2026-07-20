"""Slash command registry and parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlashCommand:
    """User-facing REPL command metadata."""

    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("help", "/help", "Show available slash commands.", ("h",)),
    SlashCommand("status", "/status", "Show current runtime and session status."),
    SlashCommand("tools", "/tools", "List tools available in the current tool profile."),
    SlashCommand("clear", "/clear", "Create a new empty session."),
    SlashCommand("exit", "/exit", "Exit the interactive REPL.", ("quit",)),
)


def command_help_text() -> str:
    lines = ["Commands:"]
    for command in SLASH_COMMANDS:
        lines.append(f"{command.usage:<16} {command.description}")
    return "\n".join(lines)


def resolve_command(name: str) -> SlashCommand | None:
    normalized = str(name or "").strip().lstrip("/").lower()
    if not normalized:
        return None
    for command in SLASH_COMMANDS:
        if normalized == command.name or normalized in command.aliases:
            return command
    return None


def suggest_commands(text: str, limit: int = 8) -> list[SlashCommand]:
    raw = str(text or "")
    if not raw.startswith("/"):
        return []
    body = raw[1:]
    if " " in body:
        return []
    token = body.lower()
    matches: list[SlashCommand] = []
    for command in SLASH_COMMANDS:
        names = (command.name, *command.aliases)
        if not token or any(name.startswith(token) for name in names):
            matches.append(command)
    return matches[:limit]
