"""Tests for scripts/send-thread-directive.py."""

import os
import sys

import pytest

# -- helpers ----------------------------------------------------------------


def _make_env(hermes_dir):
    """Create a minimal ~/.hermes/.env with a fake token."""
    env_dir = hermes_dir / ".hermes"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    env_file.write_text("DISCORD_BOT_TOKEN=fake_test_token_123\n", encoding="utf-8")
    return env_file


def _redirect_home(monkeypatch, tmp_path):
    """Redirect ~ to tmp_path so os.path.expanduser('~/.hermes/...') resolves under tmp_path."""
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) + p[1:])


def _stub_discord_tool(gateway_dir, content=None):
    """Create a stub tools/discord_tool.py under gateway_dir so imports resolve."""
    tools_dir = gateway_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "__init__.py").write_text("", encoding="utf-8")
    if content is None:
        content = 'def discord_core(action, channel_id, content):\n    return \'{"message_id": "fake_reply"}\'\n'
    (tools_dir / "discord_tool.py").write_text(content, encoding="utf-8")


def _setup_main(load_script, monkeypatch, tmp_path):
    """Common setup: env file, redirect home, stub discord_tool, load module."""
    _make_env(tmp_path)
    _redirect_home(monkeypatch, tmp_path)

    # Stub discord_tool at tmp_path/.hermes/hermes-agent/tools/discord_tool.py
    # because send_directive() does sys.path.insert(0, expanduser("~/.hermes/hermes-agent"))
    gateway_dir = tmp_path / ".hermes" / "hermes-agent"
    _stub_discord_tool(gateway_dir)

    module = load_script("scripts/send-thread-directive.py")
    return module


# -- test internals ---------------------------------------------------------


def test_module_constants(load_script):
    """Verify thread registry consistency."""
    module = load_script("scripts/send-thread-directive.py")
    assert len(module.THREADS) == 9
    # Every entry should have a 2-tuple value
    for _tid, (repo_name, local_path) in module.THREADS.items():
        assert "/" in repo_name, f"{repo_name} is not org/repo format"
        assert local_path.startswith("~/Developer/")
    # Every thread ID maps back
    for _tid in module.THREADS:
        assert _tid in module.REPO_TO_THREAD.values()


def test_repo_to_thread_mapping(load_script):
    """Verify REPO_TO_THREAD maps short names correctly."""
    module = load_script("scripts/send-thread-directive.py")
    # Known repo short names
    assert "pink-binder" in module.REPO_TO_THREAD
    assert "hermes-infra" in module.REPO_TO_THREAD
    assert "model-gateway" in module.REPO_TO_THREAD
    # 9 threads -> 9 short names
    assert len(module.REPO_TO_THREAD) == 9


def test_resolve_token_success(load_script, monkeypatch, tmp_path):
    """resolve_token reads DISCORD_BOT_TOKEN from ~/.hermes/.env."""
    _make_env(tmp_path)
    _redirect_home(monkeypatch, tmp_path)
    module = load_script("scripts/send-thread-directive.py")
    token = module.resolve_token()
    assert token == "fake_test_token_123"


def test_resolve_token_missing_file(load_script, monkeypatch, tmp_path):
    """resolve_token exits when ~/.hermes/.env does not exist."""
    _redirect_home(monkeypatch, tmp_path)
    module = load_script("scripts/send-thread-directive.py")
    with pytest.raises(SystemExit, match="1"):
        module.resolve_token()


def test_resolve_token_missing_variable(load_script, monkeypatch, tmp_path):
    """resolve_token exits when DISCORD_BOT_TOKEN is not in .env."""
    env_dir = tmp_path / ".hermes"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    env_file.write_text("OTHER_VAR=hello\n", encoding="utf-8")
    _redirect_home(monkeypatch, tmp_path)
    module = load_script("scripts/send-thread-directive.py")
    with pytest.raises(SystemExit, match="1"):
        module.resolve_token()


def test_resolve_token_empty_value(load_script, monkeypatch, tmp_path):
    """resolve_token exits when DISCORD_BOT_TOKEN is empty."""
    env_dir = tmp_path / ".hermes"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    env_file.write_text("DISCORD_BOT_TOKEN=\n", encoding="utf-8")
    _redirect_home(monkeypatch, tmp_path)
    module = load_script("scripts/send-thread-directive.py")
    with pytest.raises(SystemExit, match="1"):
        module.resolve_token()


def test_send_directive(load_script, monkeypatch, tmp_path):
    """send_directive calls discord_core and returns message_id."""
    _redirect_home(monkeypatch, tmp_path)

    # Stub discord_tool at tmp_path/.hermes/hermes-agent/tools/discord_tool.py
    _stub_discord_tool(tmp_path / ".hermes" / "hermes-agent")

    # Purge stale tools modules so our stub is found
    for mod in list(sys.modules):
        if mod.startswith("tools"):
            sys.modules.pop(mod, None)

    module = load_script("scripts/send-thread-directive.py")
    msg_id = module.send_directive("test-token", "1528842363269681304", "hello")
    assert msg_id == "fake_reply"


def test_send_directive_error(load_script, monkeypatch, tmp_path):
    """send_directive propagates exceptions from discord_core."""
    _redirect_home(monkeypatch, tmp_path)

    # Different tmp_path = fresh .hermes directory
    gateway_dir = tmp_path / ".hermes" / "hermes-agent"
    _stub_discord_tool(
        gateway_dir,
        content="def discord_core(action, channel_id, content):\n"
        "    raise RuntimeError('API error')\n",
    )

    # Purge stale tools modules so our error stub is found
    for mod in list(sys.modules):
        if mod.startswith("tools"):
            sys.modules.pop(mod, None)

    module = load_script("scripts/send-thread-directive.py")
    with pytest.raises(RuntimeError, match="API error"):
        module.send_directive("test-token", "some_id", "hello")


# -- main() tests via sys.argv monkeypatch ----------------------------------


def test_main_all_threads(load_script, monkeypatch, tmp_path, capsys):
    """main() sends to all 9 threads when no --repo filter."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(module, "send_directive", lambda t, c, m: sent.append((c, m)) or "mock_id")
    monkeypatch.setattr(sys, "argv", ["send-thread-directive.py", "Test message for all threads"])
    result = module.main()
    assert result == 0
    assert len(sent) == 9
    out = capsys.readouterr().out
    assert "OK  " in out
    assert "Sent to 9 thread(s)" in out


def test_main_single_repo(load_script, monkeypatch, tmp_path, capsys):
    """main() sends to a single repo when --repo is specified."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(module, "send_directive", lambda t, c, m: sent.append(c) or "mock_id")
    monkeypatch.setattr(
        sys, "argv", ["send-thread-directive.py", "Message", "--repo", "hermes-infra"]
    )
    result = module.main()
    assert result == 0
    assert len(sent) == 1
    out = capsys.readouterr().out
    assert "OK  0xPlayerOne/hermes-infra" in out
    assert "Sent to 1 thread(s)" in out


def test_main_multiple_repos(load_script, monkeypatch, tmp_path, capsys):
    """main() sends to multiple repos when --repo is specified multiple times."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(module, "send_directive", lambda t, c, m: sent.append(c) or "mock_id")
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "Message", "--repo", "pink-binder", "--repo", "hermes-infra"],
    )
    result = module.main()
    assert result == 0
    assert len(sent) == 2


def test_main_unknown_repo(load_script, monkeypatch, tmp_path, capsys):
    """main() warns about unknown repos and exits when none are valid."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "Message", "--repo", "nonexistent-repo"],
    )
    with pytest.raises(SystemExit, match="1"):
        module.main()
    err = capsys.readouterr().err
    assert "WARNING: Unknown repo" in err
    assert "ERROR: No valid repos" in err


def test_main_no_mention_flag(load_script, monkeypatch, tmp_path, capsys):
    """main() skips the @mention when --no-mention is passed."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    messages = []

    def capture_send(token, channel_id, content):
        messages.append(content)
        return "mock_id"

    monkeypatch.setattr(module, "send_directive", capture_send)
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "hello", "--no-mention", "--repo", "hermes-infra"],
    )
    module.main()
    msg = messages[0]
    assert "<@1528604968301494282>" not in msg
    assert "-- **Ye**" in msg  # signature still present


def test_main_no_signature_flag(load_script, monkeypatch, tmp_path, capsys):
    """main() skips the Ye signature when --no-signature is passed."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    messages = []

    def capture_send(token, channel_id, content):
        messages.append(content)
        return "mock_id"

    monkeypatch.setattr(module, "send_directive", capture_send)
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "hello", "--no-signature", "--repo", "hermes-infra"],
    )
    module.main()
    msg = messages[0]
    assert "-- **Ye**" not in msg
    assert "<@1528604968301494282>" in msg  # mention still present


def test_main_both_flags(load_script, monkeypatch, tmp_path, capsys):
    """main() suppresses both mention and signature when both flags passed."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    messages = []

    def capture_send(token, channel_id, content):
        messages.append(content)
        return "mock_id"

    monkeypatch.setattr(module, "send_directive", capture_send)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "send-thread-directive.py",
            "hello",
            "--no-mention",
            "--no-signature",
            "--repo",
            "hermes-infra",
        ],
    )
    module.main()
    msg = messages[0]
    assert "<@1528604968301494282>" not in msg
    assert "-- **Ye**" not in msg
    assert msg.strip() == "hello"


def test_main_send_failure(load_script, monkeypatch, tmp_path, capsys):
    """main() reports failures when send_directive raises."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    call_count = [0]

    def failing_send(token, channel_id, content):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ValueError("rate limited")
        return "mock_id"

    monkeypatch.setattr(module, "send_directive", failing_send)
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "hello", "--repo", "pink-binder", "--repo", "hermes-infra"],
    )
    result = module.main()
    assert result == 1  # one success, one failure
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "rate limited" in err


def test_main_returns_0_when_all_succeed(load_script, monkeypatch, tmp_path, capsys):
    """main() returns 0 when all sends succeed."""
    module = _setup_main(load_script, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "send_directive", lambda t, c, m: "mock_id")
    monkeypatch.setattr(
        sys,
        "argv",
        ["send-thread-directive.py", "hello", "--repo", "hermes-infra"],
    )
    result = module.main()
    assert result == 0
    out = capsys.readouterr().out
    assert "Sent to 1 thread(s)" in out


def test_main_dunder_not_main(load_script):
    """Verify __name__ guard — module imported, not executed as __main__."""
    module = load_script("scripts/send-thread-directive.py")
    assert module.__name__ != "__main__"
