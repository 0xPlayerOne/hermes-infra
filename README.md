# hermes-infra

Hermes-specific agent guardrails, fleet maintenance, gateway configuration, and integration with
the shared [Cortana](https://github.com/0xPlayerOne/cortana) knowledge system.

Knowledge ingestion, code indexing, embeddings, long-term evidence retrieval, MCP, and the
second-brain UI are owned by Cortana. This repository deliberately does not run a parallel TEI,
Chroma, code-index, second-brain, or Hindsight stack.

## Components

| Component | Purpose |
| --- | --- |
| Cortana skill | Teaches Hermes agents to retrieve durable context before broad discovery |
| Cortana MCP config | Connects Hermes tools to Cortana's cited hybrid retrieval |
| Guardian | Blocks destructive shell operations and protects agent/runtime data |
| AGENTS.md watchdog | Audits instruction coverage across local repositories |
| MTPLX context sync | Preserves per-model local context-window preferences |
| Gateway launchd template | Supervises the Hermes gateway |
| Cron templates | Schedules maintenance unrelated to knowledge ingestion |

## Setup

```bash
git clone https://github.com/0xPlayerOne/hermes-infra.git
cd hermes-infra
cp templates/.env.example .env
./scripts/setup-python.sh
cargo build --release
```

Install and verify Cortana separately, then follow
[`docs/cortana-integration.md`](docs/cortana-integration.md). Install the portable retrieval skill
at `$HOME/.hermes/skills/cortana` and enable the Cortana MCP server in Hermes.

Install only repository-owned launchd templates:

```bash
"$HERMES_INFRA_VENV/bin/python" scripts/install_launchd.py --check
"$HERMES_INFRA_VENV/bin/python" scripts/install_launchd.py --install
```

## Directory structure

```text
hermes-infra/
├── skills/cortana/             # portable retrieval instructions
├── src/main.rs                 # MTPLX context synchronization
├── scripts/                    # guardrails and fleet maintenance
├── launchd/                    # Hermes gateway and MTPLX templates
├── cron/                       # non-ingestion Hermes schedules
├── templates/.env.example      # safe integration variables
└── docs/                       # Cortana, cron, and global setup
```

## Ownership boundary

- Cortana owns `~/.config/cortana`, `~/.local/share/cortana`, ports `6999` and `7331`, embedding
  supervision, source schedules, backups, and retrieval.
- Hermes owns its gateway, agent/runtime configuration, guardrails, and unrelated schedules.
- New knowledge sources belong in Cortana configuration. Do not add a Hermes cron prompt or a
  second vector database for them.
- Hindsight and Honcho are optional derived-memory providers evaluated behind Cortana's documented
  boundary; neither is a canonical store or a Hermes infrastructure dependency.

## Validation

```bash
npx code-foundry doctor
.venv/bin/python -m pytest --cov --cov-report=term-missing
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --all-targets
"$HERMES_INFRA_VENV/bin/python" scripts/install_launchd.py --check
curl -fsS http://127.0.0.1:7331/readyz
```

CI requires at least 80% Python line coverage and 50% Rust line coverage.

## License

AGPL-3.0-only — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
