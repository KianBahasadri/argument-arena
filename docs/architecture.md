# Runtime and extension contracts

## Layout

- `src/argument_arena/config.py`: non-secret environment settings and file-only token loading.
- `client.py`: `discord.Client`, a guild-restricted `app_commands.CommandTree`, and `/diagnostic`.
- `runtime.py`, `health.py`, `locking.py`, `logging.py`: lifecycle, local health probes, exclusive installation lock, and JSON output.
- `storage.py`: asynchronous SQLite unit of work, versioned migrations, namespaced JSON settings, snapshot, and restore.
- `infra/terraform`: existing Docker daemon deployment; no cloud or host provisioning.

One process owns one local-disk Docker volume. SQLite uses WAL, foreign keys, a five-second busy timeout, and serialized application transactions through `aiosqlite`. The bot acquires `bot.lock` before opening the database and holds it through shutdown. Maintenance commands acquire the same lock. Store this directory on a local filesystem supporting reliable OS file locks and SQLite WAL; NFS/shared network filesystems and multi-replica deployment are outside this architecture.

The data directory contains `arena.sqlite3`, its SQLite WAL/SHM files when active, `bot.lock`, and `health.json`. It contains no token. Keep it stable across restarts and image replacements. Docker initializes a new named volume from the image's directory with UID/GID 10001 ownership; restore the same ownership when importing data. The image root is read-only in deployment, `/tmp` is a bounded tmpfs, all capabilities are dropped, and no ports are exposed.

## Persistence API for dependent features

The runtime opens `Storage` before constructing `ArenaClient`, available as `client.storage` for feature handlers. `get(namespace, key, default=None)` and `put(namespace, key, JSON_value)` provide a durable, namespaced JSON settings interface. For example, a future server setting can use namespace `guild:<snowflake>` without sharing keys with another domain. These calls do not implement any proposed product setting or consent behavior.

Use `async with storage.transaction() as db:` for atomic feature writes and parameterized `await db.execute(sql, parameters)` statements. Exceptions, including cancellation, roll back the transaction. Transactions serialize on one async lock; do not nest them, call `get`/`put` inside them, call `executescript` (it can commit implicitly), or hold a transaction across Discord/provider requests. Outside transactions, use the settings methods; raw `connection` access is reserved for schema work/tests. Schema-specific repositories should use the same transaction interface as they are introduced. Persist Discord IDs as text in product tables to retain the full unsigned snowflake range.

Append `Migration(next_version, "descriptive_name", (sql_statement, ...))` to `MIGRATIONS`. Versions start at 1 and remain contiguous. Applied version/name/SQL checksum tuples are recorded in `schema_migrations`; never rewrite an applied migration. All pending statements and migration records commit atomically at startup or `argument-arena migrate`. A failed migration rolls back, and a changed, missing, or unknown migration prevents startup. Add offline tests for each feature migration and its failure paths. Prefer additive changes; use an expand/migrate/contract sequence before removing fields used by an older image.

`argument-arena --data-dir PATH backup DESTINATION` uses SQLite's backup API, includes WAL contents, checks integrity, and refuses to overwrite a snapshot. `restore SOURCE` stages a snapshot, validates integrity and migration compatibility, applies supported pending migrations, and atomically replaces the stopped database. Both CLI commands require the bot to be stopped and hold the lock. Retain snapshots outside the bot's state volume. Never copy only `arena.sqlite3` while it is open. The [operator procedure](deployment.md#backup-and-restore) covers container mounts and safe rollback.

## Adding commands and services

Register new commands in the command tree during client construction or `setup_hook`, then synchronize once during login. Do not register, migrate, or create background jobs in `on_ready`; it repeats after reconnects. Start future workers under the runtime supervisor so exceptions close the process and shutdown cancels them. Use the configured guild guard and add explicit authorization for every mutating command. The diagnostic's Administrator restriction is the only implemented command policy.

Use `discord.AllowedMentions.none()` unless a feature explicitly needs controlled mentions. Interaction errors use ephemeral generic messages and constant log events. New provider secrets must follow the same external-file mounting pattern as the Discord token; their values must never enter Terraform, image arguments, committed configuration, settings tables, or logs. No LLM or research provider has been selected.

Python runtime dependencies are pinned directly in `pyproject.toml` and transitively with SHA-256 hashes in `requirements.txt`; build tools and development dependencies have separate hash locks. The container pins Python's multi-platform base index by digest. Terraform pins its Docker provider exactly and commits official provider checksums for common Linux, macOS, and Windows operator platforms. These are input/build locks, not a claim that rebuilt OCI metadata is byte-for-byte identical across different builder engines.
