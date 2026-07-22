import io
import sys

import pytest


def touch(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["Cargo.toml"], "rust"),
        (["package.json"], "typescript"),
        (["pyproject.toml"], "python"),
        (["package.json", "pyproject.toml"], "mixed-ts-py"),
        (["contract.sol"], "solidity"),
        (["project.csproj"], "unity-cs"),
        (["README.md"], "unknown"),
    ],
)
def test_watchdog_detect_stack(load_script, tmp_path, files, expected):
    module = load_script("scripts/agents_md_watchdog.py")
    for filename in files:
        touch(tmp_path / filename)
    assert module.detect_stack(tmp_path) == expected


def test_watchdog_git_roots_stops_at_repository(load_script, tmp_path):
    module = load_script("scripts/agents_md_watchdog.py")
    touch(tmp_path / "one" / ".git" / "config")
    touch(tmp_path / "one" / "nested" / ".git" / "config")
    touch(tmp_path / "two" / ".git" / "config")
    assert module.git_roots(tmp_path) == [tmp_path / "one", tmp_path / "two"]


def test_watchdog_main_reports_full_coverage(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    repo = tmp_path / "repo"
    touch(repo / ".git" / "config")
    touch(repo / "AGENTS.md", "covered")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    module.main()
    assert "100%" in capsys.readouterr().out


def test_watchdog_main_stamps_supported_gap(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    repo = tmp_path / "repo"
    touch(repo / ".git" / "config")
    touch(repo / "Cargo.toml")
    calls = []
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    module.main()
    output = capsys.readouterr().out
    assert "gaps found: 1" in output
    assert "stamped: yes" in output
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["Cargo.toml"], "rust"),
        (["package.json", "bun.lock"], "typescript"),
        (["pyproject.toml", "uv.lock"], "python"),
        (["foundry.toml", "src/a.sol"], "solidity"),
        (["project.csproj"], "unity-cs"),
        (["package.json", "pyproject.toml"], "mixed-ts-py"),
        ([], "unknown"),
    ],
)
def test_repo_standardize_detection(load_script, tmp_path, files, expected):
    module = load_script("scripts/repo_standardize.py")
    for filename in files:
        touch(tmp_path / filename)
    assert module.primary_lang(module.detect(tmp_path)) == expected


def test_repo_standardize_templates(load_script):
    module = load_script("scripts/repo_standardize.py")
    stacks = ["rust", "typescript", "python", "solidity", "unity-cs", "mixed-ts-py", "unknown"]
    signals = {"bun_lock": True, "npm_lock": False, "uv": True, "sol_tool": "foundry.toml"}
    for stack in stacks:
        text = module.agents_md(stack, signals, "fixture")
        assert text.startswith("# AGENTS.md")
        assert "## Stack" in text


def test_repo_standardize_main_check_does_not_write(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/repo_standardize.py")
    touch(tmp_path / "Cargo.toml")
    monkeypatch.setattr(sys, "argv", ["standardize", "--check", str(tmp_path)])
    module.main()
    assert not (tmp_path / "AGENTS.md").exists()
    assert "dry-run, not written" in capsys.readouterr().out


def test_repo_standardize_main_write_and_skip(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/repo_standardize.py")
    touch(tmp_path / "Cargo.toml")
    monkeypatch.setattr(sys, "argv", ["standardize", str(tmp_path)])
    module.main()
    assert (tmp_path / "AGENTS.md").exists()
    module.main()
    assert "exists" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["Cargo.toml"], "rust"),
        (["package.json"], "typescript"),
        (["pyproject.toml"], "python"),
        (["a.sol"], "solidity"),
        (["a.cs"], "unity-cs"),
        (["package.json", "pyproject.toml"], "mixed-ts-py"),
        ([], "unknown"),
    ],
)
def test_mise_detection_and_toml(load_script, tmp_path, files, expected):
    module = load_script("scripts/mise_toml_gen.py")
    for filename in files:
        touch(tmp_path / filename)
    stack = module.detect(tmp_path)
    assert stack == expected
    assert module.toml_for(stack).startswith("[tools]")


def test_mise_main_print_write_and_skip(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/mise_toml_gen.py")
    touch(tmp_path / "Cargo.toml")
    monkeypatch.setattr(sys, "argv", ["mise", str(tmp_path)])
    module.main()
    assert 'rust = "1.97.1"' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["mise", str(tmp_path), "--write"])
    module.main()
    assert (tmp_path / ".mise.toml").exists()
    module.main()
    assert "SKIP" in capsys.readouterr().out


def test_agents_gen_file_stdin_force_and_skip(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_gen.py")
    body = tmp_path / "body.md"
    touch(body, "## Local\nDetails")
    monkeypatch.setattr(sys, "argv", ["gen", str(tmp_path), "--body", str(body)])
    module.main()
    output = tmp_path / "AGENTS.md"
    assert "## Global Constitution" in output.read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as skipped:
        module.main()
    assert skipped.value.code == 0
    assert "SKIP" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("## Replaced"))
    monkeypatch.setattr(sys, "argv", ["gen", str(tmp_path), "--body", "-", "--force"])
    module.main()
    assert "## Replaced" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("argv", [["gen"], ["gen", "/missing", "--body", "-"]])
def test_agents_gen_bad_args(load_script, monkeypatch, argv):
    module = load_script("scripts/agents_md_gen.py")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "stdin", io.StringIO("body"))
    with pytest.raises(SystemExit):
        module.main()
