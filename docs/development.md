# Development

## Local environment

The package requires Python 3.12. `pyproject.toml` pins runtime and development
dependencies; runtime, development and build requirements are separately locked
with hashes. Install the local environment with:

```bash
bash scripts/setup-dev.sh
```

This creates `.venv`, installs `requirements-dev.txt` using hash verification,
installs the package editable without resolving dependencies, and runs `pip check`.
Use `.venv/bin/python` or activate the environment for subsequent work.

`scripts/lock-dependencies.sh` regenerates all three lock files using pip-tools.
Terraform CLI version `1.13.5` is pinned in `.terraform-version`.
`scripts/ensure-terraform.py` prefers that exact installed version or downloads a
checksum-verified platform build into ignored `.tools/`.

## Code map

| Files | Responsibility |
| --- | --- |
| `client.py`, `commands.py` | Service composition, Discord events and slash entry points |
| `arena.py`, `discord_gateway.py`, `match_ui.py` | [Match flow](matches.md) and Discord effects |
| `settings.py`, `config.py`, `admin_ui.py`, `settings_ui.py` | [Configuration](configuration.md) |
| `assistance.py`, `providers.py` | [AI services](ai-services.md) |
| `training.py`, `curriculum.py` | [Training](training.md) |
| `profiles.py`, `competition.py`, `member_ui.py` | [Member features](profiles-and-ratings.md) |
| `repository.py`, `storage.py` | SQL and serialized transactions |
| `worker.py`, `runtime.py`, `health.py`, `locking.py`, `logging.py`, `cli.py` | [Operations](operations.md) |
| `ui.py`, `messages.py`, `help_ui.py` | Shared panels, rendering and safe guidance |

`Panel` and `Form` enforce panel owner, guild and 15-minute lifetime checks.
`Confirm` serializes one-use confirmations. `FeatureControls` uses Discord layout
components, while ordinary controls use views and native select menus. Services
remain the authorization boundary even when menus hide unauthorized actions.
`respond` renders saved structures into readable ephemeral output, suppresses
mentions and attaches oversized text as `details.txt`. Unexpected failures expose
a correlation ID rather than private error payloads.

## Persistence

`Storage` opens SQLite in WAL mode with foreign keys and a 5-second busy timeout.
A mutex serializes `BEGIN IMMEDIATE` transactions. Errors and cancellation roll
back; transactions must not nest. Network/provider requests stay outside them.

Migrations are ordered, contiguous and append-only. Their names and statement
checksums are recorded in `schema_migrations`; changed history or a newer schema
refuses startup. Version 1 provides namespaced settings. Version 2 provides
documents, matches, events, official messages/revisions, claims, durable jobs,
results, rating changes, usage counters and training sessions.

`Repository.unit` exposes a transactional `Unit`. Matches persist a JSON document
alongside indexed ID/guild/channel/state/created columns; channel IDs are unique.
Configuration, consent, progress, delivery acknowledgments and worker clocks use
namespaced JSON documents. Jobs use stable IDs with insert-if-absent semantics.
See [operations](operations.md) for job execution and backup procedures.

## Validation

Run the complete gate with:

```bash
PYTHON=.venv/bin/python bash scripts/validate.sh
```

It checks Python version and installed dependencies, Ruff lint/format, the complete
pytest suite, actual offline Discord command schemas and feature coverage,
Markdown, both Terraform adapters, package building and the container smoke test.
Terraform validation uses temporary copies, readonly dependency locks and mocked
Docker tests; it never consumes operator tfvars, state or kubeconfig. YAML decoding
explicitly checks that secret file mode is decimal 288, equivalent to octal 0440.

The offline pytest suite forbids real Discord HTTP requests. Fakes provide clocks,
LLM/search responses and gateway effects. Coverage includes state transitions,
concurrent matching, message/claim revisions, recovery, permissions, privacy,
judgment and rating races, provider transport/security, migrations, runtime health,
rendered infrastructure and tool bootstrapping.

For focused feedback:

```bash
.venv/bin/python -m pytest tests/test_lfg.py tests/test_commands.py
.venv/bin/python scripts/check-product-contract.py
```

`scripts/check-container.py` builds the actual non-root image and tests offline LFG
opening/matching, persisted results/training across containers, backup, restore and
health behavior with networking disabled. Deployment and the GitHub pipeline are
documented in [operations](operations.md).
