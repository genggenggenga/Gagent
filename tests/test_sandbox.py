import subprocess
from pathlib import Path

import pytest

from gagent.features.sandbox import SandboxConfig, SandboxRunner


def test_sandbox_off_runs_plain_command(tmp_path: Path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="hi\n", stderr="")

    runner = SandboxRunner(SandboxConfig(mode="off"), run_process=fake_run)

    result = runner.run("echo hi", cwd=tmp_path, timeout=3)

    assert result.stdout == "hi\n"
    assert calls[0][0][0] == "echo hi"
    assert calls[0][1]["shell"] is True


def test_best_effort_sandbox_degrades_when_backend_unavailable(tmp_path: Path):
    events = []

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="hi\n", stderr="")

    runner = SandboxRunner(
        SandboxConfig(mode="best_effort", backend="bubblewrap"),
        which=lambda _name: None,
        run_process=fake_run,
        emit_event=lambda event, payload: events.append((event, payload)),
    )

    result = runner.run("echo hi", cwd=tmp_path, timeout=3)

    assert result.returncode == 0
    assert events[0][0] == "sandbox_unavailable"


def test_required_sandbox_fails_closed_when_backend_unavailable(tmp_path: Path):
    runner = SandboxRunner(
        SandboxConfig(mode="required", backend="bubblewrap"),
        which=lambda _name: None,
    )

    with pytest.raises(RuntimeError, match="sandbox required but unavailable"):
        runner.run("echo hi", cwd=tmp_path, timeout=3)


def test_bubblewrap_backend_builds_sandbox_argv(tmp_path: Path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    runner = SandboxRunner(
        SandboxConfig(mode="required", backend="bubblewrap", workspace_write=False),
        which=lambda _name: "/usr/bin/bwrap",
        run_process=fake_run,
    )

    runner.run("echo hi", cwd=tmp_path, timeout=3)

    argv = calls[0][0][0]
    assert argv[0] == "/usr/bin/bwrap"
    assert "--ro-bind" in argv
    assert str(tmp_path.resolve()) in argv
    assert argv[-3:] == ["/bin/sh", "-lc", "echo hi"]
