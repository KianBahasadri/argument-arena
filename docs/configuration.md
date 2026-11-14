# Runtime configuration

Both Docker and Guaranine run the installed `argument-arena` command from `src/argument_arena`. The runtime reads environment variables and mounted secret files; it does not automatically load `.env`.

| Variable | Purpose |
| --- | --- |
| `AA_GUILD_ID` | Required intended Discord server ID; other guilds are rejected |
| `AA_DISCORD_TOKEN_FILE` | Required path to a UTF-8 file containing the bot token |
| `AA_DATA_DIR` | Persistent data directory; default `.state`, `/var/lib/argument-arena` in the image |
| `AA_SYNC_COMMANDS` | Register guild commands at login; default `true` |
| `AA_LOG_LEVEL` | Standard logging level; default `INFO` |
| `AA_LLM_KEY_FILE` | Optional mounted OpenAI-compatible provider key |
| `AA_SEARCH_KEY_FILE` | Optional mounted Brave Search key |
| `AA_LLM_MODEL` | Default model identifier; example `gpt-4.1-mini` |
| `AA_LLM_ENDPOINT` | HTTPS Chat Completions endpoint; default `https://api.openai.com/v1/chat/completions` |

See [getting started](getting-started.md) for local configuration, [product policy](product.md) for server defaults, match switches, provider quotas and profile consent, and [commands](commands.md) for the executable command surface.

Use [Docker deployment](deployment.md) or the [Guaranine walkthrough](guaranine.md) for mounted credentials, persistence, health checks and recovery. Neither deployment target stores token values in Terraform. The older `arena` package and its environment-variable names were superseded during consolidation; no live installation or database from that implementation had been deployed.
