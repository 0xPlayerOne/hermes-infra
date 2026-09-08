import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_performance_budgets.py"
SPEC = importlib.util.spec_from_file_location("check_performance_budgets", SCRIPT)
performance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(performance)


def test_static_performance_budgets_pass():
    budgets = performance.load_toml(performance.BUDGETS_PATH)
    metrics = performance.static_metrics(budgets)

    assert metrics == {
        "python_requires": ">=3.11,<3.12",
        "python_direct_dependencies": 6,
        "rust_direct_dependencies": 2,
        "rust_resolved_dependencies": 17,
    }


def test_check_max_reports_regressions():
    performance.check_max("example", 3, 3)

    with pytest.raises(RuntimeError, match="example: 4 exceeds budget 3"):
        performance.check_max("example", 4, 3)


def test_percentile_uses_nearest_rank():
    assert performance.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.8) == 4.0


def test_measure_runs_checked_command(monkeypatch):
    calls = []
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(performance.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        performance.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert performance.measure(["example"], env={"KEY": "value"}) == 2.5
    assert calls == [
        (["example"], {"cwd": performance.ROOT, "env": {"KEY": "value"}, "check": True})
    ]


def test_python_metrics_checks_isolated_environment(tmp_path, monkeypatch):
    budgets = performance.load_toml(performance.BUDGETS_PATH)
    measured = iter([0.4, 1.7])

    def fake_run(command, **_kwargs):
        if command[:2] == ["uv", "venv"]:
            environment = Path(command[-1])
            (environment / "bin").mkdir(parents=True)
            (environment / "payload").write_bytes(b"1234")
        if "list" in command:
            return SimpleNamespace(stdout=json.dumps([{"name": str(index)} for index in range(25)]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(performance.subprocess, "run", fake_run)
    monkeypatch.setattr(performance, "measure", lambda *_args, **_kwargs: next(measured))

    metrics = performance.python_metrics(tmp_path, budgets)

    assert metrics == {
        "python_resolved_dependencies": 25,
        "python_environment_bytes": 4,
        "python_install_seconds": 0.4,
        "python_test_seconds": 1.7,
    }


def test_rust_metrics_checks_binary_and_startup(tmp_path, monkeypatch):
    budgets = performance.load_toml(performance.BUDGETS_PATH)
    measured = iter([3.1, 2.9])
    ticks = iter(range(0, 100_000_000, 1_000_000))

    def fake_measure(command, *, env=None):
        if "build" in command:
            binary = Path(env["CARGO_TARGET_DIR"]) / "release" / "hermes-infra"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"x" * 599_072)
        return next(measured)

    monkeypatch.setattr(performance, "measure", fake_measure)
    monkeypatch.setattr(performance.time, "perf_counter_ns", lambda: next(ticks))
    monkeypatch.setattr(
        performance.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    metrics = performance.rust_metrics(tmp_path, budgets)

    assert metrics["rust_release_binary_bytes"] == 599_072
    assert metrics["rust_cold_release_build_seconds"] == 3.1
    assert metrics["rust_cold_test_seconds"] == 2.9
    assert metrics["runtime_startup_median_ms"] == 1.0
    assert metrics["runtime_startup_p95_ms"] == 1.0


def test_rust_metrics_rejects_runtime_contract_change(tmp_path, monkeypatch):
    budgets = performance.load_toml(performance.BUDGETS_PATH)

    def fake_measure(command, *, env=None):
        if "build" in command:
            binary = Path(env["CARGO_TARGET_DIR"]) / "release" / "hermes-infra"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"x")
        return 0.1

    monkeypatch.setattr(performance, "measure", fake_measure)
    monkeypatch.setattr(
        performance.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    with pytest.raises(RuntimeError, match="unexpected no-argument exit code: 0"):
        performance.rust_metrics(tmp_path, budgets)


def test_main_emits_combined_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        performance.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: contextlib.nullcontext(tmp_path),
    )
    monkeypatch.setattr(performance, "static_metrics", lambda _budgets: {"static": 1})
    monkeypatch.setattr(performance, "python_metrics", lambda *_args: {"python": 2})
    monkeypatch.setattr(performance, "rust_metrics", lambda *_args: {"rust": 3})
    monkeypatch.setattr(
        performance.argparse.ArgumentParser,
        "parse_args",
        lambda _parser: SimpleNamespace(static_only=False),
    )

    assert performance.main() == 0
    assert json.loads(capsys.readouterr().out) == {"python": 2, "rust": 3, "static": 1}
