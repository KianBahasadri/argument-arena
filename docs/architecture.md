# Runtime and extension contracts

## Layout

- `src/argument_arena/config.py`: non-secret environment settings and file-only token loading.
- `client.py`, `commands.py`: guild-restricted Gateway, slash commands, ephemeral responses and settings UI.
- `settings.py`, `arena.py`: validated policy, authorization and transactional match state machine.
- `repository.py`, `worker.py`: durable units of work, unique leased jobs and supervised scheduling.
- `assistance.py`, `providers.py`: grounded claim graphs, evidence histories, JSON LLM/search adapters and judging.
- `competition.py`: deterministic Elo replay and filtered records.
- `curriculum.py`, `training.py`, `profiles.py`: original drills, grading/progress and consent-controlled observations.
- `discord_gateway.py`: explicit permission policy, channel creation/moves, history recovery and delivery acknowledgement.
- `runtime.py`, `health.py`, `locking.py`, `logging.py`: lifecycle, local health probes, exclusive installation lock, and JSON output.
- `storage.py`: asynchronous SQLite unit of work, versioned migrations, namespaced JSON settings, snapshot, and restore.
- `infra/terraform`: existing Docker daemon deployment; no cloud or host provisioning.

One process owns one local-disk Docker volume. SQLite uses WAL, foreign keys, a five-second busy timeout, and serialized application transactions through `aiosqlite`. The bot acquires `bot.lock` before opening the database and holds it through shutdown. Maintenance commands acquire the same lock. Store this directory on a local filesystem supporting reliable OS file locks and SQLite WAL; NFS/shared network filesystems and multi-replica deployment are outside this architecture.

The data directory contains `arena.sqlite3`, its SQLite WAL/SHM files when active, `bot.lock`, and `health.json`. It contains no token. Keep it stable across restarts and image replacements. Docker initializes a new named volume from the image's directory with UID/GID 10001 ownership; restore the same ownership when importing data. The image root is read-only in deployment, `/tmp` is a bounded tmpfs, all capabilities are dropped, and no ports are exposed.

## Persistence API for dependent features

The runtime opens `Storage` before constructing `ArenaClient`, available as `client.storage` for feature handlers. `get(namespace, key, default=None)` and `put(namespace, key, JSON_value)` provide a durable, namespaced JSON settings interface. For example, a future server setting can use namespace `guild:<snowflake>` without sharing keys with another domain. Product tables use the same unit of work; `documents` stores versioned domain JSON, including guild policy and profile consent, separately from the foundation settings namespace.

Use `async with storage.transaction() as db:` for atomic feature writes and parameterized `await db.execute(sql, parameters)` statements. Exceptions, including cancellation, roll back the transaction. Transactions serialize on one async lock; do not nest them, call `get`/`put` inside them, call `executescript` (it can commit implicitly), or hold a transaction across Discord/provider requests. Outside transactions, use the settings methods; raw `connection` access is reserved for schema work/tests. Schema-specific repositories should use the same transaction interface as they are introduced. Persist Discord IDs as text in product tables to retain the full unsigned snowflake range.

Append `Migration(next_version, "descriptive_name", (sql_statement, ...))` to `MIGRATIONS`. Versions start at 1 and remain contiguous. Applied version/name/SQL checksum tuples are recorded in `schema_migrations`; never rewrite an applied migration. All pending statements and migration records commit atomically at startup or `argument-arena migrate`. A failed migration rolls back, and a changed, missing, or unknown migration prevents startup. Add offline tests for each feature migration and its failure paths. Prefer additive changes; use an expand/migrate/contract sequence before removing fields used by an older image.

`argument-arena --data-dir PATH backup DESTINATION` uses SQLite's backup API, includes WAL contents, checks integrity, and refuses to overwrite a snapshot. `restore SOURCE` stages a snapshot, validates integrity and migration compatibility, applies supported pending migrations, and atomically replaces the stopped database. Both CLI commands require the bot to be stopped and hold the lock. Retain snapshots outside the bot's state volume. Never copy only `arena.sqlite3` while it is open. The [operator procedure](deployment.md#backup-and-restore) covers container mounts and safe rollback.

## Adding commands and services

Register new commands in the command tree during client construction or `setup_hook`, then synchronize once during login. Do not register, migrate, or create background jobs in `on_ready`; it repeats after reconnects. The durable worker runs under the existing runtime supervisor; fatal failures close the process and shutdown cancels it. Use the configured guild guard and add explicit authorization for every mutating command. Product services enforce participant, staff and Administrator authority at execution. Profile visibility also applies to staff. See [commands](commands.md).

Use `discord.AllowedMentions.none()` unless a feature explicitly needs controlled mentions. Interaction errors use ephemeral generic messages and constant log events. New provider secrets must follow the same external-file mounting pattern as the Discord token; their values must never enter Terraform, image arguments, committed configuration, settings tables, or logs. Runtime providers are OpenAI-compatible JSON Chat Completions and Brave Web Search plus bounded HTTPS retrieval, configured by non-secret environment values and optional mounted key files. Provider calls are protocols injected in tests; no service I/O occurs inside a transaction.

Python runtime dependencies are pinned directly in `pyproject.toml` and transitively with SHA-256 hashes in `requirements.txt`; build tools and development dependencies have separate hash locks. The container pins Python's multi-platform base index by digest. Terraform pins its Docker provider exactly and commits official provider checksums for common Linux, macOS, and Windows operator platforms. These are input/build locks, not a claim that rebuilt OCI metadata is byte-for-byte identical across different builder engines.

## Product persistence and recovery

Migration 2 adds additive `documents`, `matches`, `events`, `messages`, immutable `message_versions`, `claims`, `jobs`, `results`, `rating_changes`, `usage` and `training` tables. Migration 1 remains unchanged. Product SQL lives behind `Repository`/`Unit`; JSON serialization rejects nonfinite values. Snowflakes remain text. Accepted settings, rating policy, confirmations, speaker/deadline, pauses, negotiated actions, audience votes and transcript version are one aggregate saved atomically with events/jobs.

Claim IDs include message/revision/index; edits mark old claims stale rather than rewriting their source. Research check histories retain sources, verdict revisions and disputes. Jobs have unique keys, states, due times, expiring leases, attempts and safe failure codes. Waiting for evidence releases the lease without consuming provider retries. Running jobs become reclaimable after 180 seconds; the single-process lock prevents competing workers. Side effects occur outside transactions, followed by durable acknowledgement. Discord create/delivery markers recover uncertain successes. Results have a unique match key; rating replay is atomic with result changes.

A worker heartbeat is persisted separately from local process health. Unobserved/disconnected intervals extend live response deadlines conservatively. On readiness/reconnect, channel history is reconciled before forfeits are enabled. Paused/judging transcripts are also checked for edits/deletions. See [clock and outcome policy](product.md#channels-and-durable-lifecycle). Profile deletion removes generated documents and records a cutoff; deferred or amended-result jobs recheck consent and cutoff before generating anything.

Use a pre-upgrade snapshot when rolling back to the foundation-only image: it correctly refuses the newer product schema. No down migration discards product records. All new tables participate in the existing SQLite snapshot/restore and container-volume recovery procedure.
