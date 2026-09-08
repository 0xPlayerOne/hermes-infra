# Performance and release gates

Milestone M0 establishes reproducible budgets for the Rust binary, Python maintenance suite,
dependency footprint, and command startup. The measurements below are baselines, not promises
that every machine or hosted runner will reproduce the same wall-clock time.

## Baseline

The local baseline was recorded on 2026-09-07 on Apple Silicon with Python 3.11.15, Rust 1.97.1,
Cargo 1.97.1, and uv 0.12.9. Cold measurements used new temporary build and virtual-environment
directories; startup used 30 no-argument invocations of the release binary.

| Path | Baseline |
| --- | ---: |
| Rust cold release build | 3.07 s |
| Rust cold test build and 6 tests | 2.86 s |
| Rust release binary | 599,072 bytes |
| Rust dependencies | 2 direct / 17 resolved |
| Python clean install | 0.48 s |
| Python test suite | 1.78 s wall / 1.14 s pytest |
| Python test result | 150 passed / 2 live skipped / 97% coverage |
| Python dependencies | 6 direct / 25 resolved |
| Python clean virtual environment | 99,317,652 logical bytes / 50,008 KiB allocated |
| Release command startup | 3.03 ms median / 3.50 ms p95 |

The Python metadata warning came from using uv project commands against a tool-only
`pyproject.toml` with no `project.requires-python`. The repository now declares an unmanaged,
non-package Python project constrained to the same Python 3.11 line used by mise, Ruff, and
`setup-python.sh`.
The scripts remain directly invoked and are not packaged, so this does not change runtime entry
points or dependency installation.

## CI cache baseline

[Validation run 34179227813](https://github.com/0xPlayerOne/hermes-infra/actions/runs/34179227813)
completed in 3 minutes 40 seconds. Its mise toolchain caches hit on both runner families. Python
package/environment and Cargo package/build caches missed after dependency and runtime-pin changes;
CodeQL's Python database cache hit. The longest paths were Rust CodeQL (2 minutes 43 seconds), the
unit job (1 minute 19 seconds), and the final gate wait (13 seconds).

The unit job now uses `ubuntu-latest`, matching the other native build and test jobs. This removes
the separate `ubuntu-slim` toolchain/cache family and resolves the `code-foundry doctor` warning.
The scheduled audit should be used to distinguish a normal cold miss after lock/toolchain changes
from a persistent cache-key problem.

## Regression budgets

[`performance-budgets.toml`](../performance-budgets.toml) holds reviewable limits with headroom for
hosted-runner variance. [`scripts/check_performance_budgets.py`](../scripts/check_performance_budgets.py)
uses fresh temporary directories, checks locked Rust builds, installs Python requirements into an
isolated environment, runs both test paths, measures the release artifact and startup, and removes
its temporary data on exit.

Run the complete budget locally with:

```bash
python scripts/check_performance_budgets.py
```

Dependency-count increases are intentionally fail-closed: update the corresponding budget only in
the same reviewed change that explains the new dependency. Timing and size limits are regression
ceilings, not optimization targets. Do not relax coverage thresholds to satisfy a performance gate.

## Release validation

Before merging a release-affecting pull request:

```bash
npx code-foundry doctor
python scripts/check_performance_budgets.py
.venv/bin/python -m pytest --cov --cov-report=term-missing
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --all-targets --locked
.venv/bin/python scripts/install_launchd.py --check
```

Confirm both `Validation / Gate` and `Performance Budgets / Build, test, dependencies, and startup`
pass on the final pull-request commit. The live gateway readiness probe remains an operational check
and must be run only on a host where the Hermes launchd service is installed:

```bash
curl -fsS http://127.0.0.1:7331/readyz
```

A skipped live probe is not a passing probe; record the skip and reason in the pull request. After
merge, verify the Release workflow and any generated Release Please pull request rather than
inferring release readiness from the source pull request alone.
