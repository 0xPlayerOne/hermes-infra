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
| **Code Indexer** | Semantic search over `~/Developer` repos | Free |
| **Second-Brain Sync** | GitHub, Apple Notes, Drive → Chroma | Free |
| **Hindsight** | Long-term memory recall | OpenRouter Free |
| **Guardian** | Command gatekeeper (blocks destructive ops) | N/A |
| **AGENTS.md Watchdog** | Ensures fleet-wide agent coverage | Free |

## Quick Start

```bash
# 1. Install prerequisites
brew install chromadb  # or use pip
brew install watchman  # for live file indexing

# 2. Set up TEI (Text Embeddings Inference)
# See docs/tei-setup.md

# 3. Clone and configure
git clone <this-repo> ~/Developer/hermes-infra
cp templates/.env.example .env
# Edit .env with your paths

# 4. Run the indexer
source code-index-venv/bin/activate
python code-index/indexer.py --index

# 5. Run second-brain sync
cd second-brain && python sync.py
```

## Directory Structure

```
hermes-infra/
├── code-index/
│   ├── indexer.py              # Semantic code indexer (ChromaDB)
│   └── indexer-setup.sh        # Venv + chromadb setup
├── second-brain/
│   └── scripts/
│       ├── sync.py             # Unified vault sync (GitHub/Notes/Drive)
│       ├── synthesize.py       # Weekly knowledge synthesis
│       ├── export_memories.py  # Dashboard exporter
│       └── google_sync.py      # Google Drive/Email/Calendar
├── scripts/
│   ├── tei-launch.sh           # TEI launcher with memory guardrails
│   ├── code-index-watch.sh     # Watchman-based live indexer
│   ├── agents-md-watchdog      # AGENTS.md coverage checker
│   ├── repo-standardize        # Auto-stamp AGENTS.md + mise.toml
│   ├── mise-toml-gen           # Generate .mise.toml for repos
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
- **Idempotent** — Safe to re-run any component

## License

MIT
