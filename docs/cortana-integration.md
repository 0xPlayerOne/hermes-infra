# Cortana integration

Cortana owns knowledge ingestion, Qwen embedding supervision, persistent embedding and query
caches, hybrid retrieval, MCP, HTTP/UI access, backups, and its background sync schedule. Hermes
consumes that system as a client; it does not run a parallel TEI, Chroma, code-index, second-brain,
or Hindsight service.

## Install

Install and verify Cortana from its repository:

```bash
cortana doctor
cortana service status
curl -fsS http://127.0.0.1:7331/ready
```

Install this repository's `skills/cortana` directory under `$HOME/.hermes/skills/cortana`, then
configure the Hermes MCP server with:

```yaml
command: $HOME/.local/bin/cortana
args:
  - --config
  - $HOME/.config/cortana/config.toml
  - mcp
```

Expand `$HOME` before saving the command and arguments if the client does not expand shell
variables. Keep the config path absolute because MCP clients may launch from arbitrary working
directories.

## Ownership boundary

- Cortana owns ports `6999` (its embedding provider) and `7331` (query API/UI).
- Hermes owns only its gateway, schedules unrelated to knowledge ingestion, and the portable
  Cortana retrieval skill.
- Do not restore `com.hermes.tei`, `com.hermes.code-index-watcher`, or
  `com.hermes.hindsight`. They conflict with or duplicate Cortana.
- Use `brain_status` over MCP or `/ready` over HTTP for health and freshness.
- Configure new knowledge sources in `$HOME/.config/cortana/config.toml`, not Hermes cron prompts.
