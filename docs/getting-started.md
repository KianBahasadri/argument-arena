# Run the foundation locally

The implemented surface is an asynchronous Python 3.12 / discord.py bot with `/diagnostic`, validated configuration, structured logs, graceful shutdown, and durable SQLite storage. Matches, moderation, research, judging, training, and profiles remain the proposal in [README](../README.md). No Discord connection or owner's server installation has been verified.

## Clean checkout

On a development machine with Python 3.12 and Bash:

```bash
git clone https://github.com/KianBahasadri/argument-arena.git
cd argument-arena
bash scripts/setup-dev.sh
source .venv/bin/activate
argument-arena migrate
python -m pytest
```

`migrate` initializes `.state/arena.sqlite3` without a token or network. The package supports Python 3.12 only. Setup installs the complete hash-locked development dependency set, then the editable package without resolving more dependencies. For a runtime-only install, install `requirements.txt` with `--require-hashes`, then `requirements-build.txt` with `--require-hashes`, then `pip install --no-deps --no-build-isolation .`. See [development](development.md) for the full validation prerequisites and command.

## Discord application and installation

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications). Use a dedicated application for this server. Keep its bot token private; no OAuth client secret is needed by this Gateway client.
2. Configure **Guild Install** with scopes `bot` and `applications.commands`. Select **Administrator**, permission integer `8`, as requested by the intended server's feature proposal. A server administrator installs the bot into the owner's chosen guild. The invitation format is `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot%20applications.commands&permissions=8&guild_id=GUILD_ID&disable_guild_select=true`; replace both IDs locally. See [Discord bot authorization](https://docs.discord.com/developers/topics/oauth2#bot-authorization-flow).
3. Enable Developer Mode in Discord and copy that server's guild ID. Configure this installation for that single guild. The diagnostic command requires Administrator at both its Discord default permission and its execution check; other guilds and DMs are rejected by the command tree.
4. Leave **Presence**, **Server Members**, and **Message Content** privileged intents disabled. This foundation requests only `guilds`, starting from `Intents.none()`. Slash commands arrive through the Gateway without Message Content. Future transcript features must explicitly add their required intents in code and the portal; Administrator permission does not enable privileged intents. See the [discord.py intents guide](https://discordpy.readthedocs.io/en/stable/intents.html).
5. Leave the Interactions Endpoint URL unset: this process receives application interactions through the Gateway. It does not expose an HTTP server or require inbound ports.

`AA_SYNC_COMMANDS=true` performs a guild-scoped `CommandTree.sync` once in `setup_hook` after login, before connecting the Gateway. A reconnect never synchronizes commands again. Sync replaces this application's command list in the configured guild with this build's registered commands, so use a separate development application/guild. No global commands are published. Leave synchronization enabled on first install and command changes; setting it to `false` uses already published commands. Renaming/changing the guild does not remove commands from the old guild; remove those through that application's administration when moving installations. See [discord.py command synchronization](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.app_commands.CommandTree.sync).

## Configuration and local start

Copy `.env.example` to the ignored `.env`, fill in `AA_GUILD_ID`, and create `.secrets/discord-token` through a private editor or secret manager. The file contains the raw bot token on one line, with an optional trailing newline, without an authorization scheme prefix such as `Bot`. Restrict the secret directory and file to your local user. Do not paste tokens into commands, environment variables, Terraform variables, images, or source files.

Load the example's shell-compatible settings and check them without contacting Discord:

```bash
set -a
source .env
set +a
argument-arena check-config
argument-arena run
```

`argument-arena` and `python -m argument_arena` also default to `run`. Stop with Ctrl-C or SIGTERM. Do not run a local bot concurrently with the production installation using the same application token.

| Setting | Meaning | Default |
| --- | --- | --- |
| `AA_GUILD_ID` | Positive unsigned 64-bit Discord guild ID | Required |
| `AA_DISCORD_TOKEN_FILE` | Path to a readable UTF-8 file containing one non-empty token | Required; container sets `/run/secrets/discord-token` |
| `AA_DATA_DIR` | Writable persistent directory shared by all instances of this installation | `.state`; container sets `/var/lib/argument-arena` |
| `AA_SYNC_COMMANDS` | Strict `true` or `false`, case insensitive | `true` |
| `AA_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` | `INFO` |

The environment is the configuration interface; `.env` is loaded by the shell, not automatically by the package. `--data-dir PATH` is a global option for offline maintenance and health probes, placed before the subcommand. Running the bot always uses `AA_DATA_DIR`.

`/diagnostic` returns an ephemeral version, storage availability, and Gateway latency. If it is missing, check guild/application identity, invite scopes, and `guild_commands_synchronized` logs. If startup fails, verify inputs with `check-config`, token readability, volume ownership, and the JSON `error_type`/`operation_failed` event. Error responses never echo credentials or request bodies.

## Runtime behavior

The client reconnects using discord.py's built-in reconnect/backoff behavior. Connect, ready, disconnect, resume, command failures, event failures, and shutdown produce JSON logs on stdout. The formatter redacts the loaded bot token and URLs and omits exception messages/tracebacks. Library HTTP/Gateway debug logs stay disabled even with application DEBUG logging. Future code must use constant event messages and must never log user payloads, credential values, or provider responses.

Every five seconds the event loop checks SQLite and atomically writes a local `health.json`. `argument-arena healthcheck` succeeds only when that heartbeat is at most 30 seconds old, the Gateway reports ready, and the configured guild is cached. `healthcheck --liveness` checks the heartbeat alone. Neither probe connects to Discord or reads a token. A disconnect clears readiness at the next heartbeat. Startup, graceful shutdown, and fatal errors mark the file unready. Docker uses readiness; a Discord outage can make it unhealthy while reconnect continues. Docker does not restart a process merely because its healthcheck is failing. Monitor persistent unhealthy status and inspect logs before an operator restart. A frozen loop becomes stale; fatal Gateway/login/sync, storage, or heartbeat errors exit nonzero for the restart policy.

SIGTERM/SIGINT request shutdown. The supervisor marks readiness false, closes the client with a 15-second timeout, cancels remaining tasks, and closes SQLite before releasing the data-directory lock. The deployment gives Docker 30 seconds to stop it. A crash releases the OS lock automatically. Keep one authoritative installation, Terraform state, token, and data volume; a lock cannot coordinate unrelated copies using different directories or hosts.

See [deployment and recovery](deployment.md) and the [storage/extension contract](architecture.md).
