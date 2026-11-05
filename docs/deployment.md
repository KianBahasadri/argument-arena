# Deploy and recover on the owner's server

Terraform's entry point is `infra/terraform`. It manages one Docker container, one outbound-capable network, one protected named state volume, and the digest-pinned image on an **existing** Docker daemon. It provisions no cloud resources, accounts, SSH keys, operating system, or Docker host. The server OS, hostname/identity, platform, and access details are intentionally unspecified. Live preflight, installation, readiness, and idempotence checks on that server await the owner's inputs and token; they have not been performed.

## Prerequisites and host configuration

The operator needs Python 3.12, Terraform 1.13.5, the Docker CLI, the chosen image, and access to the selected daemon. `python3 scripts/ensure-terraform.py` obtains the checksum-verified pinned CLI when needed and prints its absolute path; it requires no Python dependencies. The host must provide Linux OCI containers on `linux/amd64` or `linux/arm64`, a running Docker service with restart-on-boot behavior, durable local storage supporting SQLite WAL/file locks, and outbound DNS/HTTPS/WebSocket access to Discord. No inbound bot port is needed. A non-Linux server can supply a suitable Linux container VM; its setup and shared-path mapping belong to the host adapter, not to an assumed server OS.

Before installing, implement or select an OS-appropriate declarative host configuration following [the host adapter contract](host-adapter.md). It must establish the runtime/service, durable storage, secret directory permissions for container UID/GID **10001**, and any host-specific security labels or UID mapping. Complete and review that code after the owner supplies the platform. Do not run guessed OS package commands or remote provisioners against an unknown machine.

For SSH Docker endpoints, use a pre-existing operator SSH config/agent and independently verified `known_hosts`. Configure `BatchMode yes` and `StrictHostKeyChecking yes` for that host. The Terraform provider also enforces those options. Private keys, passwords, and known-host enrollment are external operator setup; there are no private-key or password variables in this module. Local `unix://` and `npipe://` endpoints are also accepted. The bind-mount path always refers to the **daemon's Linux filesystem**, not the operator's workstation.

Externally provision a dedicated directory containing `discord-token`, readable by mapped UID/GID 10001 only (typically directory 0700 and file 0400/0600). Use the selected host's secret manager or private operator transfer procedure. Terraform mounts the **directory** read-only at `/run/secrets`, allowing atomic replacement of a file during rotation. It never reads/uploads the contents. The token path, guild ID, image digest, and server metadata are non-secret Terraform inputs. No application secret value belongs in tfvars, provider arguments, `TF_VAR_*`, Docker environment values, build args, image layers, settings tables, or state. Future provider credentials follow the same external file pattern. Protect Terraform state and plans because they contain infrastructure metadata even though application secrets are excluded.

## Inputs and image preparation

Copy `infra/terraform/terraform.tfvars.json.example` to ignored `infra/terraform/terraform.tfvars.json`. Fill it privately only when the owner supplies the inputs. Blank example values intentionally fail preflight/variable validation.

| Variable | Required value |
| --- | --- |
| `server_os` | Owner-supplied OS/version, recorded for the adapter/operator |
| `server_identity` | Expected Docker daemon `Name`; live preflight must match it |
| `docker_host` | Explicit local socket or `ssh://user@host[:port]`; no embedded password or unsecured TCP |
| `platform` | `linux/amd64` or `linux/arm64`, matched against daemon and image |
| `image` | Bot registry reference ending in immutable `@sha256:<64 hex digits>` |
| `secrets_host_path` | Dedicated absolute directory on the daemon host; no commas/newlines |
| `guild_id` | Owner's Discord guild snowflake as a JSON string |
| `name` | Stable installation name, default `argument-arena`; keep for the lifetime of its state |
| `sync_commands` | Synchronize this application's guild command list once per login, default `true` |

Build the selected platform with `docker buildx build --platform <selected-platform> --tag <chosen-registry-reference> --push .` from a reviewed checkout, or use an existing reviewed image publication process. The registry and tag are operator inputs; this repository does not publish images automatically. Record the resulting registry digest as `image`. Use external Docker registry authentication to pull that exact digest onto the selected daemon **before** preflight; do this for every new release. Terraform uses that preloaded image and has no registry credential configuration. Keep the previous digest available locally and in the registry for rollback. Do not use the local validation image tag for deployment.

For operator commands below, set these shell variables from the reviewed private inputs; their example values remain deliberately blank:

```bash
ARENA_ENDPOINT=''
ARENA_IMAGE=''
ARENA_NAME='argument-arena'
ARENA_VOLUME='argument-arena-state'
ARENA_BACKUPS=''
```

`ARENA_BACKUPS` must be a private absolute directory on the daemon host, writable by mapped UID 10001 and stored outside the state volume. Shell commands below are workstation examples, independent of server OS; an equivalent operator shell can invoke the same Docker/Terraform interfaces.

## Preflight, plan, and install

Unset `DOCKER_CONTEXT` before both preflight and Terraform; the Docker provider can otherwise let an ambient context override the explicit endpoint. Use the private JSON file as the single source for reviewed inputs. `--offline` validates only local values. `--live` verifies the daemon's identity/platform, the preloaded image's platform, and non-root token-file access in a temporary `--network=none` container. It never connects to Discord, prints token contents, or applies Terraform. Run it only after the server inputs, external secret, host adapter, and image are ready.

```bash
unset DOCKER_CONTEXT
ARENA_TERRAFORM="$(python3 scripts/ensure-terraform.py)"
export PATH="$(dirname -- "$ARENA_TERRAFORM"):$PATH"
python3 scripts/preflight.py --vars infra/terraform/terraform.tfvars.json --offline
python3 scripts/preflight.py --vars infra/terraform/terraform.tfvars.json --live
terraform -chdir=infra/terraform init -input=false -lockfile=readonly
terraform -chdir=infra/terraform plan -input=false -out=install.tfplan
terraform -chdir=infra/terraform apply install.tfplan
```

Review the saved plan before apply. The default backend is local: keep the ignored state, its backups, and saved plans in private durable operator storage, use one authoritative checkout/state per installation, and serialize operators. Terraform takes its local backend lock during operations; use a selected backend with locking if multiple operators later need access. Never copy live state between independently active workspaces. A production backend is a later explicit choice, with any backend credentials externally provided.

Apply waits up to 120 seconds for the container to become ready. Check Docker health and JSON logs; invoke `/diagnostic` as an administrator in the configured guild. Run `terraform -chdir=infra/terraform plan -detailed-exitcode` again with unchanged inputs: exit **0** means no changes; exit **2** means review drift, and exit **1** means an error. This live idempotence check is an operator acceptance step, not something CI claims to verify.

The container has a stable name, `unless-stopped` restart policy, no ports, 256 MiB memory limit, bounded JSON log rotation, a read-only root filesystem, dropped capabilities, and a local readiness healthcheck. Docker initializes a fresh named volume with the image directory's non-root ownership. If external storage or UID mapping changes, the adapter must preserve that ownership. Never run `docker compose up`, another Terraform state, a local developer bot, or a second container using the same token in parallel. A data-directory OS lock additionally blocks duplicate processes sharing this volume.

## Restart, upgrade, and rollback

For a restart after diagnosing a problem, `docker --host "$ARENA_ENDPOINT" restart --timeout 30 "$ARENA_NAME"` sends SIGTERM and then restarts the same container. Data remains in the named volume. A manually stopped container remains stopped under `unless-stopped`; start it explicitly after maintenance. Docker marks healthcheck failures unhealthy but does not restart solely on that status; investigate persistent failures while discord.py reconnects.

For an upgrade:

1. Run the full offline validation. Build/publish and pre-pull the new digest for the selected platform; retain the old digest and its compatible snapshot.
2. Stop the container and take a backup as below. Do not run Terraform while maintenance is in progress; a real apply may start the service.
3. Change only `image` in the private inputs for a normal application release. Run preflight, plan, and review the diff.
4. Apply the reviewed plan. Terraform replaces the old container **before** creating the replacement; no create-before-destroy overlap is allowed. It retains the same volume/network, and startup applies pending migrations before login.
5. Verify readiness and `/diagnostic`, then run the unchanged-input plan to check for drift.

To roll back an image with a compatible schema, set `image` to the previous digest, pre-pull it if necessary, plan and apply. If a newer migration has run, the old build deliberately refuses unknown schema versions. Stop the new container, restore the matching pre-upgrade backup using the **old image**, and apply the old digest. Restore may lose writes made since that snapshot; record the chosen recovery point. There are no automatic down migrations.

An apply that times out or fails readiness may leave a running/restarting new container. Inspect status/logs and the saved plan; stop it before restore, fix the inputs or choose the old digest, and run a new reviewed plan. Do not repeatedly start parallel copies to work around startup errors. On authentication failures, correct the externally mounted token and restart; rotating a token requires no Terraform secret change. On migration/SQLite failure, keep the volume and snapshots intact, stop the bot, and follow recovery below.

## Backup and restore

Use the same reviewed image and volume as the installation. These maintenance containers run with networking disabled and do not mount secrets. The bot must be stopped; the package also enforces its data-directory lock. Backups contain application data and must be access-controlled and retained off-host according to the operator's policy.

```bash
docker --host "$ARENA_ENDPOINT" stop --timeout 30 "$ARENA_NAME"
docker --host "$ARENA_ENDPOINT" run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --mount "type=volume,src=$ARENA_VOLUME,dst=/var/lib/argument-arena" \
  --mount "type=bind,src=$ARENA_BACKUPS,dst=/backups" \
  "$ARENA_IMAGE" backup /backups/pre-upgrade.sqlite3
docker --host "$ARENA_ENDPOINT" start "$ARENA_NAME"
```

Use a unique snapshot filename each time; existing snapshots are never overwritten. Check backup command success before restarting/upgrading. The SQLite backup API captures a consistent database, including WAL content, then checks integrity. Transfer snapshots through the chosen external backup system and retain the corresponding image digest, schema version, private non-secret inputs, and Terraform state backup. Preserve tokens separately in the external secret manager.

For restore, stop the bot, keep a safety snapshot of current readable data, select the intended image/schema recovery point, and run:

```bash
docker --host "$ARENA_ENDPOINT" run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --mount "type=volume,src=$ARENA_VOLUME,dst=/var/lib/argument-arena" \
  --mount "type=bind,src=$ARENA_BACKUPS,dst=/backups,readonly" \
  "$ARENA_IMAGE" restore /backups/pre-upgrade.sqlite3
```

Restore verifies integrity and schema compatibility in a staged database, applies migrations supported by the chosen image, and atomically replaces the stopped database. An incompatible/corrupt snapshot fails before replacing it. Start the existing container only when its image matches the restored schema, or apply the selected rollback image. Verify readiness and `/diagnostic`. Periodically practice restoring an off-host snapshot into a **separate temporary volume with networking disabled**, validate its data, and remove that test volume afterward. Do not start a second Gateway client as a restore test.

If the host is lost, recreate the adapter-managed runtime and external secret directory, recover Terraform state and the image digest, recreate/import the named volume as appropriate, restore a compatible snapshot, and review a fresh Terraform plan before starting the bot. Do not guess resource imports or discard state on an active installation. The state volume has `prevent_destroy=true`: a full destroy or installation rename intentionally fails. Decommissioning requires a separate reviewed deletion change after off-host backups are verified; normal upgrades never remove this protection.
