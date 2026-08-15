import types

import pytest


def _gh_result(returncode=0, stderr=""):
    """Minimal stand-in for subprocess.CompletedProcess returned by gh_api_put."""
    return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


@pytest.fixture
def protections_module(load_script):
    return load_script("scripts/apply-main-protections.py")


def test_apply_protection_sends_hardened_payload(protections_module, monkeypatch):
    calls = []
    monkeypatch.setattr(
        protections_module,
        "gh_api_put",
        lambda endpoint, payload: calls.append((endpoint, payload)) or _gh_result(),
    )

    result = protections_module.apply_protection(
        "hermes-infra", "0xPlayerOne/hermes-infra", ["rust", "scripts"]
    )

    assert result is True
    assert len(calls) == 2

    protection_endpoint, protection_payload = calls[0]
    assert protection_endpoint == "repos/0xPlayerOne/hermes-infra/branches/main/protection"
    assert protection_payload["required_status_checks"] == {
        "strict": True,
        "contexts": ["rust", "scripts"],
    }
    assert protection_payload["enforce_admins"] == {"enabled": True}
    reviews = protection_payload["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == 1
    assert reviews["dismiss_stale_reviews"] is True
    assert reviews["require_code_owner_reviews"] is False
    assert reviews["require_conversation_resolution"] is True
    assert protection_payload["required_linear_history"] == {"enabled": True}
    assert protection_payload["allow_force_pushes"] == {"enabled": False}
    assert protection_payload["allow_deletions"] == {"enabled": False}
    assert protection_payload["restrictions"] is None

    mq_endpoint, mq_payload = calls[1]
    assert mq_endpoint == "repos/0xPlayerOne/hermes-infra/merge-queue"
    assert mq_payload["merge_queue"]["merge_method"] == "squash"
    assert mq_payload["merge_queue"]["required"] is False
    assert mq_payload["merge_queue"]["check_response_timeout_minutes"] == 30


def test_apply_protection_returns_false_when_protection_fails(
    protections_module, monkeypatch, capsys
):
    monkeypatch.setattr(
        protections_module,
        "gh_api_put",
        lambda endpoint, payload: (
            _gh_result(returncode=1, stderr="boom") if "protection" in endpoint else _gh_result()
        ),
    )

    result = protections_module.apply_protection("pink-binder", "0xPlayerOne/pink-binder", ["Test"])

    assert result is False
    output = capsys.readouterr().out
    assert "❌ Failed: boom" in output
    assert "Merge queue" not in output


def test_apply_protection_skips_merge_queue_when_protection_fails(protections_module, monkeypatch):
    calls = []
    monkeypatch.setattr(
        protections_module,
        "gh_api_put",
        lambda endpoint, payload: calls.append(endpoint) or _gh_result(returncode=1),
    )

    protections_module.apply_protection("v0-portfolio", "0xPlayerOne/v0-portfolio", ["Test"])

    assert calls == ["repos/0xPlayerOne/v0-portfolio/branches/main/protection"]


def test_apply_protection_warns_when_merge_queue_fails(protections_module, monkeypatch, capsys):
    monkeypatch.setattr(
        protections_module,
        "gh_api_put",
        lambda endpoint, payload: (
            _gh_result() if "protection" in endpoint else _gh_result(returncode=1, stderr="nope")
        ),
    )

    result = protections_module.apply_protection(
        "v0-portfolio", "0xPlayerOne/v0-portfolio", ["Test"]
    )

    assert result is True
    output = capsys.readouterr().out
    assert "✅ Main protection applied" in output
    assert "⚠️  Merge queue: nope" in output


def test_main_applies_protection_to_every_registry_repo(protections_module, monkeypatch):
    calls = []
    monkeypatch.setattr(
        protections_module,
        "gh_api_put",
        lambda endpoint, payload: calls.append(endpoint) or _gh_result(),
    )

    protections_module.main()

    protection_calls = [e for e in calls if "/branches/main/protection" in e]
    assert len(protection_calls) == len(protections_module.REPOS)
    assert len(calls) == len(protections_module.REPOS) * 2
    for _name, remote, _checks in protections_module.REPOS:
        assert f"repos/{remote}/branches/main/protection" in protection_calls


# -- apply-staging-protections tests -----------------------------------------


def test_staging_main_applies_to_all_repos(load_script, monkeypatch, capsys):
    module = load_script("scripts/apply-staging-protections.py")
    calls = []
    monkeypatch.setattr(
        module,
        "gh_api_put",
        lambda endpoint, payload: calls.append(endpoint) or _gh_result(),
    )

    result = module.main()
    assert result == 0
    assert len(calls) == len(module.REPOS)
    for _name, remote in module.REPOS:
        assert f"repos/{remote}/branches/staging/protection" in calls


def test_staging_main_handles_403_error(load_script, monkeypatch, capsys):
    module = load_script("scripts/apply-staging-protections.py")
    monkeypatch.setattr(
        module,
        "gh_api_put",
        lambda endpoint, payload: _gh_result(returncode=1, stderr="403 Forbidden"),
    )

    result = module.main()
    assert result == 0
    output = capsys.readouterr().out
    assert "GitHub Free limitation" in output


def test_staging_main_handles_other_error(load_script, monkeypatch, capsys):
    module = load_script("scripts/apply-staging-protections.py")
    monkeypatch.setattr(
        module,
        "gh_api_put",
        lambda endpoint, payload: _gh_result(returncode=1, stderr="boom"),
    )

    result = module.main()
    assert result == 0
    output = capsys.readouterr().out
    assert "❌ Failed: boom" in output
