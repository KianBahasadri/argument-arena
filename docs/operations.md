# Operations

## Runtime and health

`argument-arena` defaults to `run`. `runtime.run` reads configuration, acquires the
data-directory `bot.lock`, opens storage and supervises Discord, the durable worker,
heartbeat and shutdown tasks. A fatal task/storage failure stops the process and
clears readiness. SIGINT/SIGTERM trigger graceful client/task cleanup while the
lock remains held through database activity.

The worker loops every 15 seconds. Jobs are leased in batches of up to ten for
180 seconds and can be reclaimed after lease expiry. Retryable errors use capped
exponential delays and stop after five attempts. Evidence-wait deferrals do not
consume retry attempts. Staff can requeue failed match jobs; training owners can
retry their own failed grading. Connection recovery behavior belongs to
[matches](matches.md).

Notices have per-piece delivery markers and database acknowledgments. On ambiguous
delivery, the gateway searches channel history for the marker before resending.
Messages are split at 1700 characters and suppress mentions.

`health.json` is atomically refreshed every five seconds. Probes require a heartbeat
no older than 30 seconds; readiness also requires a ready configured Discord guild.
Health probes do not load Discord, read tokens or open a network listener.
JSON logs contain time, level, logger and event; URLs and known secrets are
redacted, and exceptions expose class names without traceback payloads.

## Maintenance

CLI utilities:

```bash
argument-arena check-config
argument-arena healthcheck
argument-arena healthcheck --liveness
argument-arena --data-dir /path/to/state migrate
argument-arena --data-dir /path/to/state backup /path/to/new-backup.sqlite3
argument-arena --data-dir /path/to/state restore /path/to/backup.sqlite3
```

`check-config` is offline. Migrate, backup and restore require the bot to be stopped
and acquire the same process lock. Backup uses SQLite's backup API, includes WAL
contents, checks integrity and refuses an existing destination. Restore validates
and migrates a staged snapshot before atomically replacing the stopped database;
incompatible or corrupt backups leave current data intact. Keep backups and live
state outside Git.

## Images and CI

The Dockerfile builds from a digest-pinned Python 3.12 slim image, installs hashed
dependencies and the package, then runs as UID/GID 10001. State lives at
`/var/lib/argument-arena`; credentials mount read-only at `/run/secrets`.
The default entry point is `argument-arena run` with a local healthcheck.
`.dockerignore` admits only the package/build inputs.

`.github/workflows/clusterfork-validation.yml` validates pushes, pull requests and
manual runs on Ubuntu with Python 3.12. A successful push/manual run on the
canonical repository's `main` branch publishes:

```text
ghcr.io/kianbahasadri/argument-arena:sha-<full-commit-sha>
```

Publication builds `linux/amd64`, labels the source revision, pulls the published
digest and smoke-tests `--help` with networking disabled. The workflow summary
records the deployable digest. Feature completion includes successful validation,
publication, deployment and readiness verification, as required by `AGENTS.md`.

## Guaranine Kubernetes

`infra/` is the Kubernetes Terraform target. `infra/resources.yaml.tftpl` defines
the shared manifests; `scripts/render_manifests.py` renders them for kubectl use.
Use the operator's active default kubeconfig. The namespace is `argument-arena`,
the deployment/container is `bot`, and the deployment has one replica with
`Recreate` strategy to prevent overlapping clients sharing state.

The `data` PVC requests 1 GiB from `openebs-hostpath` with ReadWriteOnce access.
Its storage placement and availability are properties of the cluster's local
volume. Pod UID/GID/fsGroup 10001 allow database writes; root filesystems are
read-only, capabilities are dropped, privilege escalation is disabled and
seccomp uses RuntimeDefault. Service account token automounting is disabled.
The bot is outbound-only and defines no Service or Ingress.

Namespace networking denies ingress/egress by default, then allows DNS and public
HTTPS. Startup/liveness probes use `healthcheck --liveness`; readiness uses
`healthcheck`. The template sets resource requests/limits and graceful shutdown.

Terraform inputs include image, guild ID, kubeconfig path, optional pull-secret
name, provider model/endpoint and credential revision. It creates the namespace,
credentials Secret and manifest resources. Secret data uses Terraform write-only
arguments populated from ignored `.secrets/` files. Increment `credentials_revision`
after rotating files to upload credentials and restart the pod. Never commit
tfvars, tfstate, kubeconfig or secret values.

For an image-only rollout, obtain the digest from the successful publication run,
update the operator's saved image input if Terraform manages the installation,
then apply it to the running deployment:

```bash
kubectl -n argument-arena set image deployment/bot bot=ghcr.io/kianbahasadri/argument-arena@sha256:<digest>
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
kubectl -n argument-arena exec deployment/bot -- argument-arena healthcheck
kubectl -n argument-arena logs deployment/bot --tail=30
```

Verify the pod runs the requested digest, is Ready, synchronizes guild commands
when enabled and reaches `gateway_ready`. If the rollout fails, inspect pod events
and safe logs before reverting to the previously recorded published digest.
Do not remove the PVC during an application rollout.

## Docker Terraform adapter

`infra/terraform/` is a separate supported Docker target. Its example variable file
is intentionally blank for server-specific inputs. Operators must supply the
daemon identity/OS, explicit Docker endpoint, architecture, digest-pinned image,
guild ID and a pre-provisioned secret directory on the runtime host.

`scripts/preflight.py --vars <private-file> --offline` validates inputs without
contacting Docker. `--live` additionally checks the selected daemon identity,
image architecture and an isolated `check-config` container. An ambient
`DOCKER_CONTEXT` is refused. SSH uses external keys and strict host verification.

The adapter uses a persistent protected named volume, outbound network, read-only
root filesystem, non-root user, bounded logs and stop-before-create replacement.
Credentials mount by path and are not uploaded into Terraform state. It publishes
no ports. Optional LLM/search switches only control file references; provider
behavior remains as described in [AI services](ai-services.md).
