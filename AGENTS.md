# Hermes Infrastructure

Local-first Hermes infrastructure: Rust supervisors, Python data workflows, and shell policy/bootstrap.

## Source Of Truth

- Implementations belong in this repository; `~/.hermes` and `~/Library/LaunchAgents` contain runtime state, secrets, compatibility symlinks, and rendered plists.
- Use `scripts/install_launchd.py --check` to detect launchd drift; use `--install` only after reviewing rendered changes.
- Never commit `.env`, virtualenvs, Chroma/Hindsight state, credentials, or rendered machine-specific plists.
- Read `docs/global-setup.md` before changing global Hermes wiring.

## Toolchains

- Rust is pinned by `rust-toolchain.toml`/`mise.toml`; the Rust CLI is `target/release/hermes-infra`.
- Run `./scripts/setup-python.sh` with `uv`; it creates `.venv` for Chroma/data workflows and `.hindsight-venv` for Hindsight because their `tokenizers` requirements conflict.
- Load local settings when running services or cron-equivalent commands: `set -a; source .env; set +a`.

## Architecture

- Rust subcommands own TEI supervision, Watchman polling/indexer orchestration, Hindsight startup, and MTPLX synchronization.
- Python owns ChromaDB, Google APIs, PDF/vault transforms, repository utilities, and tests; Python files use `snake_case.py`.
- Shell is limited to Guardian policy, environment/bootstrap, and simple maintenance; shell files use `kebab-case.sh`.
- TEI must bind to `127.0.0.1:6999`; Hindsight uses `9177`. Do not reintroduce Ollama or the deleted subscription-based Watchman loop.

## Verification

Run the focused checks in this order:

```bash
cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
.venv/bin/python -m compileall -q code-index second-brain/scripts scripts tests
bash -n scripts/*.sh
.venv/bin/python -m pytest -q --cov --cov-fail-under=80
.venv/bin/python scripts/install_launchd.py --check
```

Rust coverage uses `cargo llvm-cov --fail-under-lines 50`. Live launchd checks are opt-in: `HERMES_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_live_infra.py`; they require local TEI, Hindsight, and watcher services.
