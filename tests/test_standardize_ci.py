import pytest


@pytest.fixture
def standardize_module(load_script, monkeypatch, tmp_path):
    """Load standardize-ci-dependabot.py with REPOS redirected to tmp_path."""
    module = load_script("scripts/standardize-ci-dependabot.py")
    repos = {name: str(tmp_path / name) for name in module.REPOS}
    monkeypatch.setattr(module, "REPOS", repos)
    return module


def test_write_ci_creates_file(standardize_module, tmp_path):
    standardize_module.write_ci("hermes-infra", standardize_module.BUN_CI_TEMPLATE)
    expected = tmp_path / "hermes-infra" / ".github" / "workflows" / "ci.yml"
    assert expected.exists()
    content = expected.read_text(encoding="utf-8")
    assert "Build, Format, Lint & Type Check" in content
    assert "actions/checkout@v7" in content


def test_write_dependabot_creates_file(standardize_module, tmp_path):
    standardize_module.write_dependabot("hermes-infra", standardize_module.HERMES_INFRA_DEPENDABOT)
    expected = tmp_path / "hermes-infra" / ".github" / "dependabot.yml"
    assert expected.exists()
    content = expected.read_text(encoding="utf-8")
    assert "pip" in content
    assert "cargo" in content


def test_write_ci_creates_nested_dirs(standardize_module, tmp_path):
    """os.makedirs creates nested .github/workflows directory."""
    standardize_module.write_ci("hermes-infra", standardize_module.BUN_CI_TEMPLATE)
    assert (tmp_path / "hermes-infra" / ".github" / "workflows").exists()


def test_write_dependabot_creates_nested_dirs(standardize_module, tmp_path):
    """os.makedirs creates nested .github directory."""
    standardize_module.write_dependabot("hermes-infra", standardize_module.HERMES_INFRA_DEPENDABOT)
    assert (tmp_path / "hermes-infra" / ".github").exists()


def test_write_ci_strips_leading_newline(standardize_module, tmp_path):
    """Content passed through write_ci should have leading newline stripped."""
    content = "\nname: CI\non: push\n"
    standardize_module.write_ci("hermes-infra", content)
    expected = tmp_path / "hermes-infra" / ".github" / "workflows" / "ci.yml"
    assert expected.read_text(encoding="utf-8") == "name: CI\non: push\n"


def test_write_dependabot_strips_leading_newline(standardize_module, tmp_path):
    """Content passed through write_dependabot should have leading newline stripped."""
    content = "\nversion: 2\nupdates: []\n"
    standardize_module.write_dependabot("hermes-infra", content)
    expected = tmp_path / "hermes-infra" / ".github" / "dependabot.yml"
    assert expected.read_text(encoding="utf-8") == "version: 2\nupdates: []\n"


def test_write_ci_prints_confirmation(standardize_module, tmp_path, capsys):
    standardize_module.write_ci("hermes-infra", standardize_module.BUN_CI_TEMPLATE)
    output = capsys.readouterr().out
    assert "hermes-infra: CI written" in output


def test_write_dependabot_prints_confirmation(standardize_module, tmp_path, capsys):
    standardize_module.write_dependabot("hermes-infra", standardize_module.HERMES_INFRA_DEPENDABOT)
    output = capsys.readouterr().out
    assert "hermes-infra: dependabot written" in output


def test_write_file_shared_helper(standardize_module, tmp_path):
    """write_file is the shared helper behind write_ci/write_dependabot."""
    standardize_module.write_file(
        "hermes-infra", ".github/custom.yml", "\nname: custom\n", "custom"
    )
    expected = tmp_path / "hermes-infra" / ".github" / "custom.yml"
    assert expected.read_text(encoding="utf-8") == "name: custom\n"
