import plistlib


def test_render_templates_and_active_paths(load_script, tmp_path, monkeypatch):
    module = load_script("scripts/install_launchd.py")
    module.ROOT = tmp_path / "repo"
    module.TEMPLATE_DIR = module.ROOT / "launchd"
    module.TEMPLATE_DIR.mkdir(parents=True)
    template = module.TEMPLATE_DIR / "com.test.plist.example"
    template.write_bytes(plistlib.dumps({
        "Label": "com.test",
        "ProgramArguments": ["/path/to/hermes-infra/target/release/hermes-infra"],
        "WorkingDirectory": "/path/to/.hermes",
    }))
    values = {"HERMES_HOME": str(tmp_path / "hermes"),
              "HERMES_LAUNCH_AGENTS_DIR": str(tmp_path / "agents")}
    document = plistlib.loads(module.render(template, values))
    assert document["ProgramArguments"][0] == str(module.ROOT / "target/release/hermes-infra")
    assert document["WorkingDirectory"] == str(tmp_path / "hermes")
    assert module.active_path(template, values) == tmp_path / "agents" / "com.test.plist"


def test_load_env_and_check_missing_drift(load_script, tmp_path, monkeypatch, capsys):
    module = load_script("scripts/install_launchd.py")
    env = tmp_path / ".env"
    env.write_text("# comment\nROOT=one\nQUOTED=\"two\"\n", encoding="utf-8")
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
