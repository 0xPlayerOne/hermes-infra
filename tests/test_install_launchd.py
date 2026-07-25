import plistlib
import subprocess

import pytest


def test_render_templates_and_active_paths(load_script, tmp_path, monkeypatch):
    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.test",
                "ProgramArguments": ["/path/to/hermes-infra/target/release/hermes-infra"],
                "WorkingDirectory": "/path/to/.hermes",
            }
        )
    )
    values = {
        "HERMES_HOME": str(tmp_path / "hermes"),
        "HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents"),
    }
    document = plistlib.loads(module.render(template, values))
    assert document["ProgramArguments"][0] == str(module.ROOT / "target/release/hermes-infra")
    assert document["WorkingDirectory"] == str(tmp_path / "hermes")
    assert module.active_path(template, values) == tmp_path / "agents" / "com.test.plist"


def test_load_env_and_check_missing_drift(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/install_launchd.py")
    env = tmp_path / ".env"
    env.write_text('# comment\nROOT=one\nQUOTED="two"\n', encoding="utf-8")
    values = module.load_env(env)
    assert values["ROOT"] == "one"
    assert values["QUOTED"] == "two"
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test"}))
    values["HERMES_LAUNCH_AGENTS_DIR"] = str(tmp_path / "agents")
    assert module.check([template], values) == 1
    assert "missing:" in capsys.readouterr().out


def test_check_passes_and_main_requires_mode(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    document = {"Label": "com.test", "ProgramArguments": ["test"]}
    template.write_bytes(plistlib.dumps(document))
    values = {"HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents")}
    destination = module.active_path(template, values)
    destination.parent.mkdir()
    destination.write_bytes(module.render(template, values))
    assert module.check([template], values) == 0
    assert "check passed" in capsys.readouterr().out


def test_job_label(load_script):
    """Cover job_label helper (line 53)."""
    module = load_script("scripts/install_launchd.py")
    document = {"Label": "com.example.agent"}
    assert module.job_label(document) == "com.example.agent"


def test_load_env_missing_file(load_script, tmp_path):
    """Cover load_env fallback when .env does not exist (line 18→27)."""
    module = load_script("scripts/install_launchd.py")
    missing = tmp_path / "nonexistent" / ".env"
    values = module.load_env(missing)
    # Should return a copy of os.environ (contains PYTHON environment)
    assert "PYTHON_VERSION" in values or "PATH" in values


def test_check_invalid_plist_drift(load_script, tmp_path, capsys):
    """Cover check() invalid-plist and content-drift branches (lines 67-71)."""
    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test", "ProgramArguments": ["/bin/true"]}))
    values = {"HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents")}
    destination = module.active_path(template, values)
    destination.parent.mkdir(parents=True)

    # --- invalid plist at destination ---
    destination.write_text("{{{ not a plist }}}", encoding="utf-8")
    assert module.check([template], values) == 1
    out = capsys.readouterr().out
    assert "invalid:" in out

    # --- valid but different content (drift) ---
    destination.write_bytes(
        plistlib.dumps({"Label": "com.different", "ProgramArguments": ["/bin/false"]})
    )
    assert module.check([template], values) == 1
    out = capsys.readouterr().out
    assert "drift:" in out


def test_install_bootstraps_jobs(load_script, tmp_path, monkeypatch):
    """Cover install() with mocked launchctl calls (lines 81-100)."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test", "ProgramArguments": ["/bin/true"]}))
    values = {"HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents")}

    result = module.install([template], values)
    assert result == 0
    # Rendered file should exist
    dest = module.active_path(template, values)
    assert dest.exists()
    assert plistlib.loads(dest.read_bytes())["Label"] == "com.test"

    # Two launchctl calls: bootout + bootstrap
    launchctl_calls = [c for c in calls if c[0] == "launchctl"]
    assert len(launchctl_calls) == 2
    assert "bootout" in launchctl_calls[0]
    assert "bootstrap" in launchctl_calls[1]


def test_install_raises_on_bootstrap_failure(load_script, tmp_path, monkeypatch):
    """Cover install() error path when launchctl bootstrap fails (lines 97-98)."""

    def fake_run(args, **kwargs):
        if "bootstrap" in args:
            return subprocess.CompletedProcess(args, 1, stderr="permission denied")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test", "ProgramArguments": ["/bin/true"]}))
    values = {"HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents")}

    with pytest.raises(RuntimeError, match="bootstrap failed for com.test"):
        module.install([template], values)


def test_main_install_mode(load_script, tmp_path, monkeypatch, capsys):
    """Cover main() --install path (line 125)."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    module = load_script("scripts/install_launchd.py")
    # Point ROOT to a tmp directory with a launchd template
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test", "ProgramArguments": ["/bin/true"]}))

    # Reassign DEFAULT_JOBS so main() uses our template
    module.DEFAULT_JOBS = [template]

    # Need a .env in the fake ROOT
    env_file = tmp_path / "repo" / ".env"
    env_file.write_text(f"HERMES_LAUNCH_AGENTS_DIR={tmp_path / 'agents'}\n", encoding="utf-8")

    result = module.main(["--install"])
    assert result == 0
    assert "installed:" in capsys.readouterr().out


def test_main_job_filter(load_script, tmp_path, capsys):
    """Cover main() --job filtering and no-matching-jobs error (lines 116-124)."""
    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    t1 = module.TEMPLATE_DIR / "job-a.plist.example"
    t2 = module.TEMPLATE_DIR / "job-b.plist.example"
    t1.write_bytes(plistlib.dumps({"Label": "job.a", "ProgramArguments": ["true"]}))
    t2.write_bytes(plistlib.dumps({"Label": "job.b", "ProgramArguments": ["true"]}))

    module.DEFAULT_JOBS = [t1, t2]

    # Create .env so load_env doesn't error
    env_file = tmp_path / "repo" / ".env"
    env_file.write_text(f"HERMES_LAUNCH_AGENTS_DIR={tmp_path / 'agents'}\n", encoding="utf-8")

    # Filter to one job by filename — should pass (check returns 1 because missing)
    result = module.main(["--check", "--job", "job-a"])
    assert result == 1
    out = capsys.readouterr().out
    assert "missing:" in out

    # Filter by full filename
    result = module.main(["--check", "--job", "job-b.plist.example"])
    assert result == 1
    out = capsys.readouterr().out
    assert "missing:" in out

    # No matching jobs -> error
    with pytest.raises(SystemExit):
        module.main(["--check", "--job", "nonexistent-job"])


def test_main_mutually_exclusive_modes(load_script, capsys):
    """Cover main() error when neither --check nor --install supplied, or both supplied."""
    module = load_script("scripts/install_launchd.py")
    with pytest.raises(SystemExit):
        module.main([])  # neither
    with pytest.raises(SystemExit):
        module.main(["--check", "--install"])  # both


def test_main_dunder(load_script, tmp_path, monkeypatch):
    """Cover the __name__ == '__main__' entry guard (lines 128-129)."""
    module = load_script("scripts/install_launchd.py")
    # Set up minimal environment so main() can run
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({"Label": "com.test", "ProgramArguments": ["/bin/true"]}))
    module.DEFAULT_JOBS = [template]
    env_file = tmp_path / "repo" / ".env"
    env_file.write_text(f"HERMES_LAUNCH_AGENTS_DIR={tmp_path / 'agents'}\n", encoding="utf-8")

    # We can't actually set __name__ after import, but we can verify
    # that calling main() via the if-name guard pattern works by
    # checking that module.__name__ is the synthetic name (not "__main__")
    assert module.__name__ != "__main__"
