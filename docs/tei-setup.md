# TEI Setup — Text Embeddings Inference on macOS

Run a local embeddings server with Qwen3-Embedding-0.6B on Apple Silicon.

## Prerequisites

- macOS on Apple Silicon (M-series)
- Homebrew installed

## 1. Install TEI

```bash
brew install text-embeddings-inference
```

This installs the `text-embeddings-router` binary at `/opt/homebrew/bin/text-embeddings-router`.

## 2. Download the Model

TEI downloads models on first run, but you can pre-cache:

```bash
# Create HuggingFace cache directory if needed
mkdir -p ~/.cache/huggingface

# The model will be pulled automatically on first launch.
# To pre-download manually (optional):
huggingface-cli download Qwen/Qwen3-Embedding-0.6B
```

## 3. Create the Launch Script

Create `$HOME/.hermes/scripts/tei-launch.sh` (see `templates/tei-launch.sh` in this repo).
Make it executable:

```bash
chmod +x $HOME/.hermes/scripts/tei-launch.sh
mkdir -p $HOME/.hermes/logs
```

The script starts TEI on port 6999 with:
- `float16` dtype for Metal acceleration
- 2 GB memory limit guard (monitors RSS every 10s, kills and restarts if exceeded)
- Conservative batch limits: 512 tokens, 16 concurrent requests

## 4. Install the launchd Service

Copy the plist template, replace `$HOME` with your actual home directory path,
then load:

```bash
# Copy and edit
cp launchd/com.hermes.tei.plist.example ~/Library/LaunchAgents/com.hermes.tei.plist
# Edit: replace all $HOME with your actual home path (e.g., /Users/yourname)
# macOS launchd does not expand $HOME — use absolute paths.

# Load the service
launchctl load ~/Library/LaunchAgents/com.hermes.tei.plist
```

To unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.hermes.tei.plist
```

## 5. Health Check

TEI takes ~45 seconds to warm up Metal on first launch. Verify readiness:

```bash
curl -s http://localhost:6999/health
# Expected: "OK" or empty 200 response

# Test embedding generation
curl -s http://localhost:6999/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "model": "Qwen/Qwen3-Embedding-0.6B"}'
```

## Logs

```bash
tail -f $HOME/.hermes/logs/tei.log
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `curl: (7) Failed to connect` | TEI still warming up — wait 45s and retry |
| Port 6999 already in use | `lsof -i :6999` to find the process |
| OOM / killed by macOS | Reduce `MAX_BATCH_TOKENS` in the launch script |
| `text-embeddings-router: command not found` | `brew install text-embeddings-inference` |
