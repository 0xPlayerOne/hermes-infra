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
    assert module.primary_lang(module.detect_signals(tmp_path)) == expected


def test_watchdog_git_roots_stops_at_repository(load_script, tmp_path):
    module = load_script("scripts/agents_md_watchdog.py")
    touch(tmp_path / "one" / ".git" / "config")
    touch(tmp_path / "one" / "nested" / ".git" / "config")
    touch(tmp_path / "two" / ".git" / "config")
    assert module.git_roots(tmp_path) == [tmp_path / "one", tmp_path / "two"]


def test_watchdog_infra_health_uses_cortana(load_script, monkeypatch):
    module = load_script("scripts/agents_md_watchdog.py")
    calls = []
    monkeypatch.setenv("WATCHDOG_INFRA_CHECKS", "1")
    monkeypatch.setattr(module, "curl_ok", lambda url: calls.append(url) or "healthy")

    assert module.infra_health() == ("healthy", "healthy")
    assert calls == [
        "http://127.0.0.1:7331/healthz",
        "http://127.0.0.1:7331/readyz",
    ]


def test_watchdog_infra_health_is_opt_in(load_script, monkeypatch):
    module = load_script("scripts/agents_md_watchdog.py")
    monkeypatch.delenv("WATCHDOG_INFRA_CHECKS", raising=False)
    monkeypatch.setattr(module, "curl_ok", lambda _url: pytest.fail("network check ran"))

    assert module.infra_health() == ("skipped", "skipped")


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
    assert module.primary_lang(module.detect_signals(tmp_path)) == expected


def test_stack_detect_sol_tool_foundry(load_script, tmp_path):
    module = load_script("scripts/stack_detect.py")
    touch(tmp_path / "foundry.toml")
    touch(tmp_path / "src" / "a.sol")
    assert module.detect_signals(tmp_path)["sol_tool"] == "foundry.toml"


def test_stack_detect_sol_tool_hardhat(load_script, tmp_path):
    module = load_script("scripts/stack_detect.py")
    touch(tmp_path / "hardhat.config.ts")
    touch(tmp_path / "contracts" / "a.sol")
    assert module.detect_signals(tmp_path)["sol_tool"] == "hardhat.config.ts"


def test_repo_standardize_solidity_template_picks_tool(load_script):
    module = load_script("scripts/repo_standardize.py")
    signals = {"bun_lock": False, "npm_lock": False, "uv": False, "sol_tool": "foundry.toml"}
    text = module.agents_md("solidity", signals, "fixture")
    assert "- **Toolchain:** Foundry (forge)" in text
    signals["sol_tool"] = "hardhat.config.ts"
    text = module.agents_md("solidity", signals, "fixture")
    assert "- **Toolchain:** Hardhat" in text


def test_repo_standardize_accepts_partial_signals(load_script):
    """agents_md tolerates sparse signal dicts (defensive .get access)."""
    module = load_script("scripts/repo_standardize.py")
    text = module.agents_md("typescript", {"bun_lock": True}, "fixture")
    assert "- **Package manager:** bun" in text
    text = module.agents_md("python", {"uv": True}, "fixture")
    assert "- **Package manager:** uv" in text
    text = module.agents_md("solidity", {}, "fixture")
    assert "- **Toolchain:** Hardhat" in text


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
    stack = module.primary_lang(module.detect_signals(tmp_path))
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


def test_repo_registry_is_complete_and_consistent(load_script):
    module = load_script("scripts/repo_registry.py")
    assert len(module.REPO_NAMES) == 9
    assert len(set(module.REPO_NAMES)) == 9  # unique display names
    assert module.REPO_REMOTES["hermes-infra"] == "0xPlayerOne/hermes-infra"
    assert module.REPO_PATHS["model-gateway"].endswith("model-gateway")
    # Every name must resolve in both derived maps.
    for name in module.REPO_NAMES:
        assert name in module.REPO_REMOTES
        assert name in module.REPO_PATHS


def test_apply_staging_uses_registry(load_script):
    module = load_script("scripts/apply-staging-protections.py")
    names = [name for name, _ in module.REPOS]
    assert names == module.REPO_NAMES
    assert ("hermes-infra", "0xPlayerOne/hermes-infra") in module.REPOS


def test_apply_main_uses_registry(load_script):
    module = load_script("scripts/apply-main-protections.py")
    names = [name for name, _, _ in module.REPOS]
    assert names == module.REPO_NAMES
    assert module.CHECKS["hermes-infra"] == ["rust", "scripts"]


def test_standardize_ci_uses_registry(load_script):
    module = load_script("scripts/standardize-ci-dependabot.py")
    assert module.REPO_PATHS["pink-binder"].endswith("pink-binder")


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


def test_github_api_put_builds_gh_call(load_script, monkeypatch):
    import subprocess

    module = load_script("scripts/github_api.py")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        result = subprocess.CompletedProcess(cmd, 0, "ok", "")
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = module.gh_api_put("repos/owner/repo/branches/main/protection", {"strict": True})
    assert result.returncode == 0
    assert len(calls) == 1
    assert calls[0][0] == [
        "gh",
        "api",
        "repos/owner/repo/branches/main/protection",
        "--method",
        "PUT",
        "-H",
        "Content-Type: application/json",
        "-f",
        'payload={"strict": true}',
    ]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    assert calls[0][1]["timeout"] == 30


def test_stack_detect_unitypackage_does_not_count_as_cs(load_script, tmp_path):
    module = load_script("scripts/stack_detect.py")
    touch(tmp_path / "pkg.unitypackage")
    sig = module.detect_signals(tmp_path)
    assert sig["cs"] == 0
    assert sig["unity"] is False
    assert module.primary_lang(sig) == "unknown"
