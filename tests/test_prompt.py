from pathlib import Path

from gagent.core.prompt import build_system_prompt, tool_signature
from gagent.core.workspace import WorkspaceContext
from gagent.tools.registry import build_builtin_registry, resolve_tool_profile


def test_system_prompt_includes_workspace_and_tool_guidance(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    tools = build_builtin_registry()
    profile = resolve_tool_profile(tools, "readonly")

    prompt = build_system_prompt(
        workspace=workspace,
        tools=tools,
        profile=profile,
        built_at="2026-07-12T00:00:00+00:00",
    )

    assert "You are Gagent" in prompt.text
    assert "Tool profile: readonly" in prompt.text
    assert "`grep`" in prompt.text
    assert "- `bash`" not in prompt.text
    assert "repo_root:" in prompt.text
    assert "### README.md" in prompt.text
    assert prompt.workspace_fingerprint == workspace.fingerprint()
    assert prompt.tool_signature == tool_signature(tools, profile)
    assert prompt.built_at == "2026-07-12T00:00:00+00:00"


def test_tool_signature_changes_with_profile(tmp_path: Path):
    workspace = WorkspaceContext.build(tmp_path)
    tools = build_builtin_registry()
    readonly = resolve_tool_profile(tools, "readonly")
    default = resolve_tool_profile(tools, "default")

    readonly_prompt = build_system_prompt(workspace=workspace, tools=tools, profile=readonly)
    default_prompt = build_system_prompt(workspace=workspace, tools=tools, profile=default)

    assert readonly_prompt.tool_signature != default_prompt.tool_signature
    assert "- `bash`" not in readonly_prompt.text
    assert "- `bash`" in default_prompt.text
