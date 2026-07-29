---
name: cortana
description: Retrieve durable personal, project, communication, calendar, email, document, and code context from Cortana. Use before broad or costly discovery when a task depends on prior decisions, preferences, project history, cross-repository code, messages, notes, meetings, or long-term agent memory.
---

# Cortana retrieval

Use the configured Cortana MCP server first. If MCP is unavailable, call the local HTTP API at
`http://127.0.0.1:7331/v1/context`; use `cortana search` only as a raw-evidence fallback.

1. Start with `context` using concrete terms and the current project when known. Its token-bounded
   Markdown is ready to place in working context and cite with `[n]`.
2. Use `search` only for raw evidence, a focused second pass, or exact details absent from the
   context bundle.
3. Use exact configured source filters. Call `brain_status` when freshness or source names are
   uncertain.
4. Reuse a context bundle within the task. Cortana persistently caches query and ingestion
   embeddings, while redundant retrieval still costs ranking and context-window work.
5. Preserve source URIs and timestamps. Prefer lexical evidence for identifiers and errors, and
   semantic evidence for paraphrases.
6. Never persist secrets, credentials, private keys, raw authentication material, or copied
   Cortana evidence outside the task unless the user asks.
7. When evidence conflicts, prefer newer authoritative sources and disclose the conflict.

Configure Hermes MCP with the installed binary and an absolute config path:

```yaml
mcp_servers:
  cortana:
    command: /absolute/path/to/cortana
    args:
      - --config
      - /absolute/path/to/cortana.toml
      - mcp
```
