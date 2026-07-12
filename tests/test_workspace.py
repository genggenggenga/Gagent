from pathlib import Path
import subprocess

import pytest

from gagent.core.workspace import PROJECT_DOC_LIMIT, WorkspaceContext


def test_workspace_falls_back_to_cwd_outside_git_repo(tmp_path: Path):
    workspace = WorkspaceContext.build(tmp_path)

    assert workspace.cwd == tmp_path.resolve()
    assert workspace.repo_root == tmp_path.resolve()
    assert workspace.git_status == "clean"


def test_workspace_discovers_git_root_from_subdirectory(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()

    workspace = WorkspaceContext.build(src)

    assert workspace.cwd == src.resolve()
    assert workspace.repo_root == tmp_path.resolve()
    assert [doc.path for doc in workspace.project_docs] == ["README.md"]


def test_workspace_resolve_path_allows_repo_root_but_rejects_escape(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    src = tmp_path / "src"
    src.mkdir()
    workspace = WorkspaceContext.build(src)

    assert workspace.resolve_path("../README.md") == (tmp_path / "README.md").resolve()
    with pytest.raises(ValueError, match="escapes workspace"):
        workspace.resolve_path("../../outside.txt")


def test_workspace_collects_and_clips_project_docs(tmp_path: Path):
    long_text = "x" * (PROJECT_DOC_LIMIT + 50)
    (tmp_path / "AGENTS.md").write_text(long_text, encoding="utf-8")

    workspace = WorkspaceContext.build(tmp_path)

    assert len(workspace.project_docs) == 1
    doc = workspace.project_docs[0]
    assert doc.path == "AGENTS.md"
    assert doc.truncated
    assert len(doc.content) <= PROJECT_DOC_LIMIT


def test_workspace_fingerprint_changes_when_project_docs_change(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("first\n", encoding="utf-8")
    first = WorkspaceContext.build(tmp_path)

    readme.write_text("second\n", encoding="utf-8")
    second = WorkspaceContext.build(tmp_path)

    assert first.fingerprint() != second.fingerprint()
