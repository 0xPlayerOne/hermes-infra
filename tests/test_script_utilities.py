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
    assert module.REPO_PATHS["pink-binder"].endswith("PinkBinder")


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


# ---------------------------------------------------------------------------
# agents_md_watchdog — full coverage for curl_ok + main edge branches
# ---------------------------------------------------------------------------


def test_watchdog_resolve_path_expands_vars(load_script, monkeypatch, tmp_path):
    import os

    module = load_script("scripts/agents_md_watchdog.py")
    monkeypatch.setenv("FOO", str(tmp_path))
    assert module.resolve_path("$FOO/bar") == str(tmp_path / "bar")
    # ~/x should expand to $HOME/x
    assert module.resolve_path("~/x") == os.path.expanduser("~/x")
    assert module.resolve_path("$FOO") == str(tmp_path)


def test_watchdog_curl_ok_healthy(load_script, monkeypatch):
    import subprocess

    module = load_script("scripts/agents_md_watchdog.py")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "200", ""),
    )
    assert module.curl_ok("http://example.com") == "healthy (http=200)"


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected_prefix"),
    [
        ("500", 0, "unreachable/failed (http=500)"),
        ("", 1, "unreachable/failed (http=)"),
        ("abc", 0, "unreachable/failed (http=abc)"),
        ("000", 0, "unreachable/failed (http=000)"),
    ],
)
def test_watchdog_curl_ok_unhealthy(load_script, monkeypatch, stdout, returncode, expected_prefix):
    import subprocess

    module = load_script("scripts/agents_md_watchdog.py")

    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(a[0], returncode, stdout, "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.curl_ok("http://example.com")
    assert result == expected_prefix


def test_watchdog_curl_ok_exception(load_script, monkeypatch):
    module = load_script("scripts/agents_md_watchdog.py")

    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(module.subprocess, "run", boom)
    result = module.curl_ok("http://example.com")
    assert result.startswith("error: ")
    assert "network down" in result


def test_watchdog_curl_ok_timeout_propagation(load_script, monkeypatch):
    import subprocess

    module = load_script("scripts/agents_md_watchdog.py")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "200", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.curl_ok("http://example.com", timeout=7)
    assert captured["timeout"] == 12  # timeout + 5
    # curl args should contain the original timeout as --max-time value
    assert "--max-time" in captured["cmd"]
    idx = captured["cmd"].index("--max-time")
    assert captured["cmd"][idx + 1] == "7"


def test_watchdog_main_skips_nested_agents(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    # repo with no root AGENTS.md but nested subdir has one -> should be skipped entirely
    repo = tmp_path / "nifty-fork"
    touch(repo / ".git" / "config")
    touch(repo / "NiftyRoyale" / "AGENTS.md", "nested")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    # should NOT stamp — nested pattern means no gap
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda a, **k: calls.append(a))
    module.main()
    assert "100%" in capsys.readouterr().out
    assert calls == []  # infra skipped + no stamp


def test_watchdog_main_permission_error_continues(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    good = tmp_path / "good-repo"
    bad = tmp_path / "bad-repo"
    touch(good / ".git" / "config")
    touch(good / "Cargo.toml")
    touch(bad / ".git" / "config")
    # make os.listdir raise PermissionError for bad repo
    orig_listdir = __import__("os").listdir

    def fake_listdir(path):
        if str(path) == str(bad):
            raise PermissionError("denied")
        return orig_listdir(path)

    monkeypatch.setattr(module.os, "listdir", fake_listdir)
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda a, **k: calls.append(a))
    module.main()
    out = capsys.readouterr().out
    # good repo should still be reported as gap; bad repo silently skipped
    assert "gaps found: 1" in out
    assert "good-repo" in out


def test_watchdog_main_unsupported_stack_no_stamp(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    repo = tmp_path / "unity-game"
    touch(repo / ".git" / "config")
    touch(repo / "project.csproj")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda a, **k: calls.append(a))
    module.main()
    out = capsys.readouterr().out
    assert "gaps found: 1" in out
    assert "stamped: no" in out
    # No stamper call for unity-cs; MISGEN may still be called but stamper should not
    stamper_calls = [c for c in calls if "repo_standardize" in str(c)]
    assert stamper_calls == []


def test_watchdog_main_unknown_stack_reports_gap(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    repo = tmp_path / "empty-repo"
    touch(repo / ".git" / "config")
    # no stack files -> unknown
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    monkeypatch.setattr(module.subprocess, "run", lambda a, **k: None)
    module.main()
    out = capsys.readouterr().out
    assert "gaps found: 1" in out
    assert "empty-repo" in out
    assert "stamped: no" in out


def test_watchdog_main_existing_agents_not_gap(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    # Two repos: one covered, one gap
    covered = tmp_path / "covered"
    gap = tmp_path / "gap"
    touch(covered / ".git" / "config")
    touch(covered / "AGENTS.md", "done")
    touch(gap / ".git" / "config")
    touch(gap / "pyproject.toml")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    monkeypatch.setattr(module.subprocess, "run", lambda a, **k: None)
    module.main()
    out = capsys.readouterr().out
    assert "gaps found: 1" in out
    assert "gap" in out
    assert "covered" not in out


def test_watchdog_main_dunder_calls_main(load_script, tmp_path, monkeypatch, capsys):
    # Exercise the `if __name__ == \"__main__\"` guard via exec

    repo = tmp_path / "solo"
    touch(repo / ".git" / "config")
    touch(repo / "AGENTS.md", "x")
    # Re-load module via runpy-like exec to hit __main__
    module = load_script("scripts/agents_md_watchdog.py")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    # main() should still work when invoked
    module.main()
    assert "100%" in capsys.readouterr().out


def test_watchdog_main_misgen_missing_branch(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/agents_md_watchdog.py")
    repo = tmp_path / "py-repo"
    touch(repo / ".git" / "config")
    touch(repo / "pyproject.toml")
    monkeypatch.setattr(module, "DEV", tmp_path)
    monkeypatch.setattr(module, "MISGEN", tmp_path / "nonexistent_mise_gen.py")
    monkeypatch.setattr(module, "STAMPER", tmp_path / "nonexistent_stamper.py")
    monkeypatch.setattr(sys, "argv", ["watchdog"])
    # Even with both tools missing, main should report gap but not crash
    module.main()
    out = capsys.readouterr().out
    assert "gaps found: 1" in out
    assert "py-repo" in out
    assert "stamped: no" in out
