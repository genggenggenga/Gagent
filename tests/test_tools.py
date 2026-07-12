from pathlib import Path

from gagent.tools.base import ToolExecutionContext
from gagent.tools.registry import build_builtin_registry, resolve_tool_profile


def test_tool_profiles_filter_capabilities():
    registry = build_builtin_registry()

    readonly = resolve_tool_profile(registry, "readonly")
    no_shell = resolve_tool_profile(registry, "no_shell")

    assert {tool.name for tool in registry.tools_for_profile(readonly)} == {
        "grep",
        "glob",
        "list_dir",
        "read_file",
    }
    assert "bash" not in {tool.name for tool in registry.tools_for_profile(no_shell)}
    assert "edit_file" in {tool.name for tool in registry.tools_for_profile(no_shell)}


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


def test_project_exploration_tools_return_workspace_results(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\nVALUE = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\nhello\n", encoding="utf-8")
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "readonly")
    context = ToolExecutionContext(cwd=tmp_path)

    list_result = registry.execute("list_dir", {"path": "."}, context, profile)
    glob_result = registry.execute("glob", {"pattern": "**/*.py"}, context, profile)
    grep_result = registry.execute("grep", {"pattern": "hello", "literal": True}, context, profile)

    assert "src/" in list_result.content
    assert "README.md" in list_result.content
    assert "src/app.py" in glob_result.content
    assert "README.md:2:hello" in grep_result.content
    assert "src/app.py:1:print('hello')" in grep_result.content


def test_grep_supports_regex_and_include_filter(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 123\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "src" / "app.txt").write_text("VALUE = 456\n", encoding="utf-8")
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "readonly")
    context = ToolExecutionContext(cwd=tmp_path)

    result = registry.execute(
        "grep",
        {"pattern": r"VALUE = \d+", "include": "*.py"},
        context,
        profile,
    )

    assert not result.is_error
    assert "src/app.py:1:VALUE = 123" in result.content
    assert "src/app.txt" not in result.content


def test_grep_literal_mode_does_not_treat_pattern_as_regex(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("a.c\nabc\n", encoding="utf-8")
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "readonly")
    context = ToolExecutionContext(cwd=tmp_path)

    result = registry.execute(
        "grep",
        {"pattern": "a.c", "literal": True},
        context,
        profile,
    )

    assert not result.is_error
    assert "notes.txt:1:a.c" in result.content
    assert "notes.txt:2:abc" not in result.content


def test_edit_file_replaces_one_unique_occurrence(tmp_path: Path):
    target = tmp_path / "notes.txt"
    target.write_text("hello world\n", encoding="utf-8")
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "default")
    context = ToolExecutionContext(cwd=tmp_path)

    result = registry.execute(
        "edit_file",
        {"path": "notes.txt", "old_text": "hello", "new_text": "hi"},
        context,
        profile,
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "hi world\n"
    assert result.metadata == {"path": "notes.txt", "replacements": 1, "byte_delta": -3}


def test_edit_file_rejects_ambiguous_replacements(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("same\nsame\n", encoding="utf-8")
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "default")
    context = ToolExecutionContext(cwd=tmp_path)

    result = registry.execute(
        "edit_file",
        {"path": "notes.txt", "old_text": "same", "new_text": "other"},
        context,
        profile,
    )

    assert result.is_error
    assert "occurs 2 times" in result.content


def test_bash_result_includes_exit_code_stdout_and_stderr(tmp_path: Path):
    registry = build_builtin_registry()
    profile = resolve_tool_profile(registry, "default")
    context = ToolExecutionContext(cwd=tmp_path)

    result = registry.execute(
        "bash",
        {"command": "printf hello && printf error >&2"},
        context,
        profile,
    )

    assert not result.is_error
    assert "exit_code: 0" in result.content
    assert "stdout:\nhello" in result.content
    assert "stderr:\nerror" in result.content
    assert result.metadata["exit_code"] == 0
