import datetime
import io
from types import SimpleNamespace


def test_run_success_and_error(load_script, monkeypatch):
    module = load_script("scripts/daily_intel.py")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=" output \n"))
    assert module.run("command") == "output"
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))
    assert module.run("command").startswith("(err:")


def test_build_briefing_all_sections(load_script):
    module = load_script("scripts/daily_intel.py")
    responses = iter([
        '[{"title":"Issue","url":"https://issue"}]',
        '[{"title":"PR","url":"https://pr"}]',
        "Reminder",
    ])
    runner = lambda command: next(responses)
    xml = b"<feed><title>feed</title><entry><title>Paper One</title></entry></feed>"
    opener = lambda *a, **k: io.BytesIO(xml)
    result = module.build_briefing(
        "user", ["repo"], "cat:test", runner, opener, datetime.date(2026, 1, 2))
    assert "January 02, 2026" in result
    assert "Issue" in result and "PR" in result
    assert "Reminder" in result and "Paper One" in result


def test_build_briefing_empty_and_bad_json(load_script):
    module = load_script("scripts/daily_intel.py")
    responses = iter(["[bad", "", ""])
    result = module.build_briefing(
        "user", ["repo"], "cat:test", lambda command: next(responses),
        lambda *a, **k: io.BytesIO(b"<feed><title>feed</title></feed>"))
    assert "no open issues/PRs" in result
    assert "gate closed" in result


def test_build_briefing_arxiv_failure(load_script):
    module = load_script("scripts/daily_intel.py")
    result = module.build_briefing(
        "", [], "cat:test", lambda command: "",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert "arxiv fetch failed" in result


def test_main_prints_briefing(load_script, monkeypatch, capsys):
    module = load_script("scripts/daily_intel.py")
    monkeypatch.setattr(module, "build_briefing", lambda: "brief")
    module.main()
    assert capsys.readouterr().out == "brief\n"
