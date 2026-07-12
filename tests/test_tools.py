from pathlib import Path

from gagent.tools.base import ToolExecutionContext
from gagent.tools.registry import build_builtin_registry, resolve_tool_profile


def test_tool_profiles_filter_capabilities():
    registry = build_builtin_registry()

    readonly = resolve_tool_profile(registry, "readonly")
    no_shell = resolve_tool_profile(registry, "no_shell")

    assert [tool.name for tool in registry.tools_for_profile(readonly)] == ["read_file"]
    assert "bash" not in {tool.name for tool in registry.tools_for_profile(no_shell)}


def test_read_and_write_file_tools_stay_inside_workspace(tmp_path: Path):
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "default")
    context = ToolExecutionContext(cwd=tmp_path)

    write_result = registry.execute(
        "write_file",
        {"path": "notes/todo.txt", "content": "hello"},
        context,
        profile,
    )
    read_result = registry.execute(
        "read_file",
        {"path": "notes/todo.txt"},
        context,
        profile,
    )
    escape_result = registry.execute(
        "read_file",
        {"path": "../outside.txt"},
        context,
        profile,
    )

    assert not write_result.is_error
    assert "hello" in read_result.content
    assert escape_result.is_error
