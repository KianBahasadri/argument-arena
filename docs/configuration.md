# Runtime configuration

Both Docker and Guaranine run the installed `argument-arena` command from `src/argument_arena`. The runtime reads environment variables and mounted secret files; it does not automatically load `.env`.

| Variable | Purpose |
| --- | --- |
| `AA_GUILD_ID` | Required intended Discord server ID; other guilds are rejected |
| `AA_DISCORD_TOKEN_FILE` | Required path to a UTF-8 file containing the bot token |
| `AA_DATA_DIR` | Persistent data directory; default `.state`, `/var/lib/argument-arena` in the image |
| `AA_SYNC_COMMANDS` | Register guild commands at login; default `true` |
| `AA_LOG_LEVEL` | Standard logging level; default `INFO` |
| `AA_LLM_KEY_FILE` | Optional mounted OpenCode Go API key |
| `AA_SEARCH_KEY_FILE` | Optional mounted Brave Search key |
| `AA_LLM_MODEL` | Default model identifier; example `claude-haiku-5-5` |
| `AA_LLM_JUDGE_MODEL` | Default judging model; `gemini-4-argon`; an explicit match model overrides it |
| `AA_LLM_ENDPOINT` | OpenCode Go endpoint; default `https://opencode.ai/inference/go/openai/v1/chat/completions` |

## OpenCode Go

OpenCode Go is the required LLM service. The async `openai` Python SDK authenticates with the key read from `AA_LLM_KEY_FILE` and sends requests to OpenCode. The key is read again for each call so mounted credential rotation takes effect. Only these endpoints are accepted:

- `https://opencode.ai/inference/go/openai/v1/chat/completions`
- `https://opencode.ai/inference/go/openai/v1/responses`

OpenCode translates requests for models whose native APIs differ. Routine assistance defaults to Claude Haiku 5.5; judging defaults to Gemini 4 Argon. An explicit model accepted in a match overrides the judging default. The server's model settings and each match's judging model select IDs from the [current Go catalog](https://opencode.ai/docs/console/go/). There is no fallback to direct providers or the pay-as-you-go Models API. Do not enable paid Extra Usage as part of deployment.

Requests include the application's user agent and a stable, hashed conversation identifier. They request low reasoning effort and are limited to 200,000 input characters, 3,000 output tokens, a 25-second overall deadline and a 2 MB response. The SDK does not retry internally; the existing durable job worker owns bounded retries and quotas. Structured JSON and task-specific validation remain mandatory. Missing keys, rejected requests, malformed output and outages produce unavailable states instead of invented assessments.

Go model processing terms differ. Contributor models that permit training on prompts are unsuitable for the bot's Discord content under its privacy policy. Synthetic evaluations do not contain Discord content and must not change the account's privacy or billing settings.

See the [model evaluation and Pareto frontier](opencode-go-models.md) for the current shortlist, prices, measured task checks and limitations.

See [getting started](getting-started.md) for local configuration, [product policy](product.md) for server defaults, match switches, provider quotas and profile consent, and [commands](commands.md) for the executable command surface.

Use [Docker deployment](deployment.md) or the [Guaranine walkthrough](guaranine.md) for mounted credentials, persistence, health checks and recovery. Neither deployment target stores token values in Terraform. The older `arena` package and its environment-variable names were superseded during consolidation; no live installation or database from that implementation had been deployed.
