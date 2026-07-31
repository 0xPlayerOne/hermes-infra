import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARDIAN = ROOT / "scripts" / "guardian.sh"


def guardian_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    tmutil = fake_bin / "tmutil"
    tmutil.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tmutil.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HERMES_HOME": str(tmp_path / "hermes"),
        "DEV_ROOT": str(tmp_path / "code"),
        "HERMES_INFRA_ENV_FILE": str(tmp_path / "missing.env"),
    }


def run_guardian(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(GUARDIAN), *args],
        check=False,
        capture_output=True,
        text=True,
        env=guardian_env(tmp_path),
    )


def test_removed_second_brain_override_is_rejected(tmp_path):
    result = run_guardian(tmp_path, "--second-brain", "printf unsafe")
    assert result.returncode == 1
    assert "unsupported option" in result.stderr


def test_protected_hermes_root_remains_blocked(tmp_path):
    hermes_root = tmp_path / "hermes"
    result = run_guardian(tmp_path, "--confirm", f"rm -rf {hermes_root}")
    assert result.returncode == 2
    assert "protected path" in result.stderr


def test_unprotected_delete_still_requires_confirmation(tmp_path):
    target = tmp_path / "scratch.txt"
    target.write_text("keep", encoding="utf-8")
    result = run_guardian(tmp_path, f"rm -f {target}")
    assert result.returncode == 4
    assert target.exists()


def test_confirmed_unprotected_delete_executes_after_snapshot(tmp_path):
    target = tmp_path / "scratch.txt"
    target.write_text("delete", encoding="utf-8")
    result = run_guardian(tmp_path, "--confirm", f"rm -f {target}")
    assert result.returncode == 0
    assert not target.exists()


def test_bare_force_push_is_blocked(tmp_path):
    result = run_guardian(tmp_path, "--confirm", "git push --force origin main")
    assert result.returncode == 1
    assert "forbidden pattern" in result.stderr

    result = run_guardian(tmp_path, "--confirm", "git push -f origin main")
    assert result.returncode == 1
    assert "forbidden pattern" in result.stderr


def test_force_with_lease_is_allowed(tmp_path):
    # The rebase discipline mandates `git push --force-with-lease`; the
    # gatekeeper must not false-positive on the bare --force substring.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    git = fake_bin / "git"
    git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    git.chmod(0o755)
    result = run_guardian(tmp_path, "--confirm", "git push --force-with-lease origin staging")
    assert result.returncode == 0
    assert "BLOCKED" not in result.stderr
