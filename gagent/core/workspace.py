"""Workspace discovery and path boundary helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

PROJECT_DOC_NAMES = ("AGENTS.md", "README.md", "pyproject.toml", "package.json")
PROJECT_DOC_LIMIT = 1200
STATUS_LIMIT = 1500
RECENT_COMMIT_LIMIT = 5


@dataclass(frozen=True)
class ProjectDocument:
    """Small workspace document snippet included in the prompt."""

    path: str
    content: str
    truncated: bool = False


@dataclass(frozen=True)
class WorkspaceContext:
    """A compact, stable snapshot of the current project workspace."""

    cwd: Path
    repo_root: Path
    branch: str
    default_branch: str
    git_status: str
    recent_commits: tuple[str, ...]
    project_docs: tuple[ProjectDocument, ...]

    @classmethod
    def build(cls, cwd: Path) -> "WorkspaceContext":
        resolved_cwd = cwd.resolve()
        repo_root = _discover_repo_root(resolved_cwd)
        return cls(
            cwd=resolved_cwd,
            repo_root=repo_root,
            branch=_git(resolved_cwd, ["branch", "--show-current"], fallback="-") or "-",
            default_branch=_default_branch(resolved_cwd),
            git_status=_clip(_git(resolved_cwd, ["status", "--short"], fallback="clean") or "clean", STATUS_LIMIT),
            recent_commits=tuple(
                line
                for line in _git(
                    resolved_cwd,
                    ["log", "--oneline", f"-{RECENT_COMMIT_LIMIT}"],
                    fallback="",
                ).splitlines()
                if line.strip()
            ),
            project_docs=_collect_project_docs(repo_root, resolved_cwd),
        )

    def resolve_path(self, raw_path: str) -> Path:
        """Resolve a user-supplied path inside the repository boundary."""

        if not raw_path:
            raise ValueError("path is required")
        path = (self.cwd / raw_path).resolve()
        if not path.is_relative_to(self.repo_root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return path

    def relative_to_root(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo_root).as_posix()

    def fingerprint(self) -> str:
        payload = {
            "cwd": str(self.cwd),
            "repo_root": str(self.repo_root),
            "branch": self.branch,
            "default_branch": self.default_branch,
            "git_status": self.git_status,
            "recent_commits": list(self.recent_commits),
            "project_docs": [
                {"path": doc.path, "content": doc.content, "truncated": doc.truncated}
                for doc in self.project_docs
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def to_prompt_section(self) -> str:
        commits = "\n".join(f"- {commit}" for commit in self.recent_commits) or "- none"
        docs = "\n\n".join(
            f"### {doc.path}\n{doc.content}" + ("\n...[truncated]" if doc.truncated else "")
            for doc in self.project_docs
        ) or "none"
        return textwrap.dedent(
            f"""\
            ## Workspace

            - cwd: {self.cwd}
            - repo_root: {self.repo_root}
            - branch: {self.branch}
            - default_branch: {self.default_branch}
            - git_status:
            {self.git_status}
            - recent_commits:
            {commits}

            ## Project Docs

            {docs}
            """
        ).strip()


def _discover_repo_root(cwd: Path) -> Path:
    root = _git(cwd, ["rev-parse", "--show-toplevel"], fallback="")
    if not root:
        return cwd
    return Path(root).resolve()


def _default_branch(cwd: Path) -> str:
    branch = _git(cwd, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], fallback="")
    if branch.startswith("origin/"):
        return branch[len("origin/") :]
    return branch or "main"


def _collect_project_docs(repo_root: Path, cwd: Path) -> tuple[ProjectDocument, ...]:
    docs: dict[str, ProjectDocument] = {}
    for base in (repo_root, cwd):
        if not base.is_relative_to(repo_root):
            continue
        for name in PROJECT_DOC_NAMES:
            path = base / name
            if not path.is_file():
                continue
            rel_path = path.relative_to(repo_root).as_posix()
            if rel_path in docs:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            snippet = _clip(content, PROJECT_DOC_LIMIT)
            docs[rel_path] = ProjectDocument(
                path=rel_path,
                content=snippet,
                truncated=len(content) > PROJECT_DOC_LIMIT,
            )
    return tuple(docs[path] for path in sorted(docs))


def _git(cwd: Path, args: list[str], *, fallback: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return fallback
    return result.stdout.strip() or fallback


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 24] + "\n... (content truncated)"
