#!/usr/bin/env python3
"""Measure reproducible Hermes build, test, dependency, and startup budgets."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
BUDGETS_PATH = ROOT / "performance-budgets.toml"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def dependency_line_count(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def check_max(name: str, actual: float, maximum: float) -> None:
    if actual > maximum:
        raise RuntimeError(f"{name}: {actual} exceeds budget {maximum}")


def percentile(samples: list[float], fraction: float) -> float:
    position = max(0, math.ceil(len(samples) * fraction) - 1)
    return sorted(samples)[position]


def measure(command: list[str], *, env: dict[str, str] | None = None) -> float:
    started = time.perf_counter()
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    return time.perf_counter() - started


def static_metrics(budgets: dict) -> dict[str, int | str]:
    pyproject = load_toml(ROOT / "pyproject.toml")
    cargo = load_toml(ROOT / "Cargo.toml")
    cargo_lock = load_toml(ROOT / "Cargo.lock")
    python_budget = budgets["python"]
    rust_budget = budgets["rust"]

    requires_python = pyproject["project"]["requires-python"]
    if requires_python != python_budget["requires_python"]:
        raise RuntimeError(
            "project.requires-python does not match performance-budgets.toml: "
            f"{requires_python!r} != {python_budget['requires_python']!r}"
        )

    metrics: dict[str, int | str] = {
        "python_requires": requires_python,
        "python_direct_dependencies": dependency_line_count(ROOT / "requirements-dev.txt"),
        "rust_direct_dependencies": len(cargo.get("dependencies", {})),
        "rust_resolved_dependencies": len(cargo_lock.get("package", [])),
    }
    check_max(
        "python direct dependencies",
        metrics["python_direct_dependencies"],
        python_budget["max_direct_dependencies"],
    )
    check_max(
        "Rust direct dependencies",
        metrics["rust_direct_dependencies"],
        rust_budget["max_direct_dependencies"],
    )
    check_max(
        "Rust resolved dependencies",
        metrics["rust_resolved_dependencies"],
        rust_budget["max_resolved_dependencies"],
    )
    return metrics


def python_metrics(temporary: Path, budgets: dict) -> dict[str, int | float]:
    python_budget = budgets["python"]
    environment = temporary / "venv"
    subprocess.run(["uv", "venv", "--python", "3.11", str(environment)], check=True)
    interpreter = environment / "bin" / "python"
    install_seconds = measure(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(interpreter),
            "--requirement",
            str(ROOT / "requirements-dev.txt"),
        ]
    )
    installed = subprocess.run(
        ["uv", "pip", "list", "--python", str(interpreter), "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    package_count = len(json.loads(installed.stdout))
    environment_bytes = sum(
        path.stat().st_size for path in environment.rglob("*") if path.is_file()
    )
    test_seconds = measure([str(interpreter), "-m", "pytest", "-q"])

    check_max(
        "Python resolved dependencies", package_count, python_budget["max_resolved_dependencies"]
    )
    check_max("Python environment bytes", environment_bytes, python_budget["max_environment_bytes"])
    check_max("Python install seconds", install_seconds, python_budget["max_install_seconds"])
    check_max("Python test seconds", test_seconds, python_budget["max_test_seconds"])
    return {
        "python_resolved_dependencies": package_count,
        "python_environment_bytes": environment_bytes,
        "python_install_seconds": round(install_seconds, 3),
        "python_test_seconds": round(test_seconds, 3),
    }


def rust_metrics(temporary: Path, budgets: dict) -> dict[str, int | float]:
    rust_budget = budgets["rust"]
    target = temporary / "target"
    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = str(target)
    build_seconds = measure(["cargo", "build", "--release", "--locked"], env=environment)
    test_seconds = measure(["cargo", "test", "--all-targets", "--locked"], env=environment)
    binary = target / "release" / ("hermes-infra.exe" if os.name == "nt" else "hermes-infra")
    binary_bytes = binary.stat().st_size

    samples = []
    for _ in range(budgets["runtime"]["startup_samples"]):
        started = time.perf_counter_ns()
        result = subprocess.run([str(binary)], capture_output=True, check=False)
        if result.returncode != 1:
            raise RuntimeError(f"unexpected no-argument exit code: {result.returncode}")
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    startup_p95_ms = percentile(samples, 0.95)

    check_max(
        "cold Rust release build seconds",
        build_seconds,
        rust_budget["max_cold_release_build_seconds"],
    )
    check_max("cold Rust test seconds", test_seconds, rust_budget["max_cold_test_seconds"])
    check_max("release binary bytes", binary_bytes, rust_budget["max_release_binary_bytes"])
    check_max(
        "runtime startup p95 milliseconds", startup_p95_ms, budgets["runtime"]["max_startup_p95_ms"]
    )
    return {
        "rust_cold_release_build_seconds": round(build_seconds, 3),
        "rust_cold_test_seconds": round(test_seconds, 3),
        "rust_release_binary_bytes": binary_bytes,
        "runtime_startup_median_ms": round(statistics.median(samples), 3),
        "runtime_startup_p95_ms": round(startup_p95_ms, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static-only", action="store_true", help="check metadata and dependency counts only"
    )
    args = parser.parse_args()
    budgets = load_toml(BUDGETS_PATH)
    metrics = static_metrics(budgets)
    if not args.static_only:
        with tempfile.TemporaryDirectory(prefix="hermes-performance-") as temporary:
            temporary_path = Path(temporary)
            metrics.update(python_metrics(temporary_path / "python", budgets))
            metrics.update(rust_metrics(temporary_path / "rust", budgets))
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
