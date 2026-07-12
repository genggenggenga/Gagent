"""Optional sandbox execution helpers for shell commands."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from shutil import which as default_which
from typing import Literal

SandboxMode = Literal["off", "best_effort", "required"]
SandboxBackend = Literal["auto", "bubblewrap", "none"]


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration for optional shell sandboxing."""

    mode: SandboxMode = "off"
    backend: SandboxBackend = "auto"
    workspace_write: bool = True
    excluded_commands: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


class SandboxRunner:
    """Run shell commands directly or inside a best-effort sandbox."""

    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        which: Callable[[str], str | None] | None = None,
        run_process: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        emit_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self.which = which or default_which
        self.run_process = run_process or subprocess.run
        self.emit_event = emit_event or (lambda _event, _payload: None)

    def run(
        self,
        command: str,
        *,
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if self.config.mode == "off" or _command_is_excluded(
            command, self.config.excluded_commands
        ):
            return self._plain(command, cwd=cwd, timeout=timeout, env=env)

        backend_path = self._backend_path()
        if not backend_path:
            self.emit_event(
                "sandbox_unavailable",
                {
                    "mode": self.config.mode,
                    "backend": self.config.backend,
                    "command": command[:200],
                },
            )
            if self.config.mode == "required":
                raise RuntimeError("sandbox required but unavailable")
            return self._plain(command, cwd=cwd, timeout=timeout, env=env)

        argv = self._bubblewrap_argv(backend_path, command, cwd.resolve())
        return self.run_process(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_shell_env(cwd, env),
            check=False,
        )

    def _plain(
        self,
        command: str,
        *,
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_shell_env(cwd, env),
            check=False,
        )

    def _backend_path(self) -> str:
        backend = "bubblewrap" if self.config.backend == "auto" else self.config.backend
        if backend == "none":
            return ""
        if backend == "bubblewrap":
            return self.which("bwrap") or ""
        return ""

    def _bubblewrap_argv(self, backend_path: str, command: str, cwd: Path) -> list[str]:
        argv = [
            backend_path,
            "--die-with-parent",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
        ]
        for path in ("/lib", "/lib64"):
            if Path(path).exists():
                argv.extend(["--ro-bind", path, path])
        bind_mode = "--bind" if self.config.workspace_write else "--ro-bind"
        argv.extend([bind_mode, str(cwd), str(cwd), "--chdir", str(cwd)])
        argv.extend(["--", "/bin/sh", "-lc", command])
        return argv


def _command_is_excluded(command: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(command.strip(), pattern) for pattern in patterns)


def _shell_env(cwd: Path, env: dict[str, str] | None) -> dict[str, str]:
    source = env or os.environ
    allowed = {
        name: value
        for name, value in source.items()
        if name
        in {
            "CI",
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "SHELL",
            "TERM",
            "TMPDIR",
            "USER",
            "VIRTUAL_ENV",
        }
    }
    allowed.setdefault("PATH", os.defpath)
    allowed["PWD"] = str(cwd)
    return allowed
