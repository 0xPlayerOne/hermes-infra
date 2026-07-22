# hermes-infra

Local-first AI infrastructure: embeddings, semantic indexing, second-brain sync, and agent guardrails — all running on zero-cost models.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    HERMES AGENT                       │
│          (CLI / Gateway / Desktop / Cron)             │
└──────┬───────────┬───────────┬───────────┬───────────┘
       │           │           │           │
       ▼           ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Hindsight│ │ ChromaDB │ │ ChromaDB │ │  Hindsight│
│  (memory) │ │(code-idx)│ │(2nd-brn) │ │ (recall) │
└─────┬────┘ └─────┬────┘ └─────┬────┘ └─────┬────┘
      │            │            │             │
      └──────┬─────┘            └──────┬──────┘
             ▼                         ▼
      ┌─────────────┐         ┌─────────────┐
      │  TEI Server  │         │  TEI Server  │
      │ Qwen3-0.6B   │         │ Qwen3-0.6B   │
      │ :6999        │         │ :6999        │
      └─────────────┘         └─────────────┘
```

## Components

| Component | Purpose | Cost |
|-----------|---------|------|
| **TEI Embeddings** | Local text embeddings (Qwen3-0.6B, 1024-dim) | Free |
| **Code Indexer** | Semantic search over `$DEV_ROOT` repos | Free |
| **Second-Brain Sync** | GitHub, Apple Notes, Drive → Chroma | Free |
| **Hindsight** | Long-term memory recall | OpenRouter Free |
| **Guardian** | Command gatekeeper (blocks destructive ops) | N/A |
| **AGENTS.md Watchdog** | Ensures fleet-wide agent coverage | Free |

## Quick Start

```bash
# 1. Install prerequisites
brew install watchman  # for live file indexing

# 2. Set up TEI (Text Embeddings Inference)
# See docs/tei-setup.md
# See docs/hindsight-setup.md for the memory service
# See docs/global-setup.md for Hermes integration and source-of-truth rules

# 3. Clone and configure
git clone <this-repo> "$HERMES_INFRA_DIR"
cp templates/.env.example .env
# Edit .env with your paths
set -a; source .env; set +a

# 4. Build the Rust infrastructure supervisor
cargo build --release

# 5. Create the isolated data and Hindsight Python environments
./scripts/setup-python.sh
source .venv/bin/activate

# 6. Run the indexer
python code-index/indexer.py --index

# 7. Run the second-brain sync
python second-brain/scripts/sync.py
```

## Directory Structure

```
hermes-infra/
├── src/
│   └── main.rs                 # Rust supervisors: TEI, watcher, MTPLX
├── code-index/
│   ├── indexer.py              # Semantic code indexer (ChromaDB)
├── second-brain/
│   └── scripts/
│       ├── sync.py             # Unified vault sync (GitHub/Notes/Drive)
│       ├── synthesize.py       # Weekly knowledge synthesis
│       ├── export_memories.py  # Dashboard exporter
│       └── google_sync.py      # Google Drive/Email/Calendar
├── scripts/
│   ├── guardian.sh             # Shell safety policy and command gate
│   ├── setup-python.sh         # Shared uv-managed Python environment
│   ├── agents_md_watchdog.py   # AGENTS.md coverage checker
│   ├── agents_md_gen.py        # Stitch generated AGENTS.md bodies
│   ├── repo_standardize.py     # Auto-stamp AGENTS.md
│   ├── mise_toml_gen.py        # Generate .mise.toml for repos
│   └── daily_intel.py          # Daily intelligence briefing
├── launchd/                    # Plist templates (sanitized)
├── cron/                       # Cron job definitions (sanitized)
├── templates/                  # Config templates
│   └── .env.example
└── docs/                       # Architecture docs
```

## Design Principles

- **Zero API costs** — TEI runs locally, Hindsight uses OpenRouter free tier
- **Live + batch** — Watchman for real-time, cron for catch-up
- **Memory guardrails** — TEI capped at 2GB RSS, auto-restart on OOM
- **Guardian-first** — All destructive ops routed through `guardian.sh`
- **Rust-first** — supervisors in Rust, data workflows in Python, shell only for bootstrap/policy
- **Idempotent** — Safe to re-run any component

## Language And Naming

The language choice is based on responsibility, not preference alone:

| Language | Use it for | Why |
|----------|------------|-----|
| **Rust** | Long-running services, process supervision, health monitoring, Watchman polling, state synchronization | Strong lifecycle/error handling, low overhead, and reliable daemon behavior |
| **Python** | ChromaDB, Google APIs, PDF extraction, vault/data transformation, plist rendering, and tests | These workflows depend on mature Python libraries and are dominated by API/data handling rather than process supervision |
| **Shell** | Guardian command policy, environment/bootstrap setup, and simple system-maintenance composition | These tasks directly intercept shell commands or orchestrate native tools such as `uv`, `cargo`, Homebrew, and `launchctl` |

All new code must follow these rules:

- Rust owns long-running infrastructure. CLI subcommands use `kebab-case`.
- Python owns data workflows and Python-library integrations. Files use `snake_case.py`.
- Shell is a last resort for bootstrap, environment loading, policy enforcement, and simple maintenance. Files use `kebab-case.sh`.
- Do not convert Python data workflows to Rust solely for language uniformity; that would replace stable library integrations with custom OAuth, HTTP, PDF, and database code.
- Do not convert Guardian or bootstrap scripts to Rust when direct shell semantics are their purpose.
- Any new executable must be classified against this table in its code review and covered by the corresponding Rust/Python test gate.

## Testing

```bash
# Python: unit tests plus branch-aware coverage
.venv/bin/python -m pytest --cov --cov-report=term-missing

# Rust: formatting, linting, tests, and instrumented coverage
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo llvm-cov --summary-only

# launchd: detect drift between repo templates and active jobs
"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/scripts/install_launchd.py" --check
```

CI enforces at least 80% Python line coverage and 50% Rust line coverage. Rust's remaining uncovered lines are primarily non-returning process supervisors and launchd/Watchman integration branches, which are validated against the live macOS services.

## License

AGPL-3.0-only — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
