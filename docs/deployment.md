# Deployment on Guaranine

The application runs one Discord gateway client. It needs outbound DNS and public HTTPS/WSS, a Discord token, and a persistent SQLite database. It needs no public port, Service, Ingress, or load balancer. The files below belong to this app repository; Guaranine's existing cluster remains managed separately.

## Before deployment

Use Python 3.12 and Docker. Connect to Tailscale and verify `kubectl get nodes`. At least one worker must be Ready. The default worker in the infrastructure configuration is `demure`; use its actual name if it changes.

In the Discord Developer Portal, create an application and bot, enable **Message Content Intent**, and install it in your server with the `bot` and `applications.commands` scopes and Administrator permission. The bot uses message content to build the official transcript. Keep its token private. Developer Mode in Discord exposes Copy Server ID for `DISCORD_GUILD_ID`.

LLM assistance uses an OpenAI-compatible HTTPS chat-completions endpoint. Research uses Tavily search and independently retrieves readable public HTTPS pages. Set credentials and a model available to your account. Match management works without these keys; unavailable AI features report their status rather than producing invented output. These providers may incur charges; no real provider calls are part of the test suite.

## Validate and build

Run from the application repository:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
bash scripts/validate.sh
```

Choose a versioned image name. Check the worker's CPU architecture before building; `docker buildx build --platform linux/amd64` is appropriate only for an amd64 worker.

```bash
kubectl get nodes -L kubernetes.io/arch
docker build -t ghcr.io/kianbahasadri/argument-arena:0.1.0 .
docker login ghcr.io
docker push ghcr.io/kianbahasadri/argument-arena:0.1.0
```

GitHub Container Registry requires package write permission for publishing. Public packages can be pulled without credentials. For a private image, create a registry Secret in the app namespace and pass its name with `--pull-secret` or Terraform's `pull_secret` variable. Never commit a registry token. The container runs as UID/GID 10001 and has a read-only root filesystem in Kubernetes.

Publishing does not automatically make a GHCR package public. Either change the package visibility in GitHub's package settings, or, after the namespace exists, create a private pull credential using a dedicated Docker configuration directory:

```bash
umask 077
arena_docker_config="$HOME/.local/state/argument-arena/docker"
mkdir -p "$arena_docker_config"
docker --config "$arena_docker_config" login ghcr.io
kubectl -n argument-arena create secret generic ghcr-pull \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=".dockerconfigjson=$arena_docker_config/config.json"
```

Enter a token with package read access at the login prompt, then render with `--pull-secret ghcr-pull` (or use Terraform's corresponding variable). The dedicated configuration must contain registry authentication rather than only a reference to a desktop credential helper. Keep this file private.

## Prepare storage on the worker

Guaranine has no default storage provisioner. This deployment explicitly uses a retained **local PersistentVolume** pinned to one worker. On that worker's host, create its backing directory with the following command, using your existing administrative access:

```bash
sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/argument-arena
```

This host command is necessary once. `/var/lib` must be persistent on that Kairos worker; confirm that before using it. The PersistentVolume is a local volume, not a hostPath mounted directly by the pod. PodSecurity restricted remains enabled.

The bot will be unavailable while that laptop sleeps or disconnects. Its database stays on that laptop and does not follow a rescheduled pod. Restored service extends response clocks for downtime. For availability across worker loss, replace this volume with an existing replicated CSI volume and restore from backup; increasing replicas is unsupported.

## Deploy with kubectl

Use this workflow or Terraform below, and keep one manager for the same resources.

```bash
python scripts/render_manifests.py \
  --image ghcr.io/kianbahasadri/argument-arena:0.1.0 \
  --worker-name demure > /tmp/argument-arena.yaml
kubectl apply --dry-run=server -f /tmp/argument-arena.yaml
```

On a first deployment the server dry run may report that the namespace does not exist, because dry-run resources are not persisted. Review the rendered file first, then create the namespace and rerun the dry run before applying the remaining resources:

```bash
kubectl create namespace argument-arena
kubectl apply --dry-run=server -f /tmp/argument-arena.yaml
kubectl apply -f /tmp/argument-arena.yaml
```

Prepare credentials outside the repository with restrictive file permissions:

```bash
umask 077
mkdir -p "$HOME/.local/state/argument-arena"
arena_credentials="$HOME/.local/state/argument-arena/bot.env"
cp .env.example "$arena_credentials"
${EDITOR:-nano} "$arena_credentials"
kubectl -n argument-arena create secret generic bot-credentials \
  --from-env-file="$arena_credentials"
```

Fill `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, and the provider configuration in that file. Environment files use plain `NAME=value` lines, without shell commands or quoting. The deployment waits for this Secret. Provider secrets are not stored in Terraform state. Guaranine encrypts Kubernetes Secrets at rest.

```bash
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
kubectl -n argument-arena get pods,pvc
kubectl -n argument-arena logs deployment/bot --tail=100
```

Run `/ping` in Discord, create the four match categories, and run `/setup`. Start a casual match with research and judging disabled for an initial infrastructure check; then enable configured AI features and verify them deliberately. See [commands](commands.md) and [configuration](configuration.md).

## Terraform alternative

`infra/` renders the same `resources.yaml.tftpl` as the kubectl workflow. It manages the namespace, PV, PVC, Deployment, and NetworkPolicies, and protects the namespace against accidental destruction. It uses an existing cluster and never creates Azure infrastructure.

```bash
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan \
  -var='image=ghcr.io/kianbahasadri/argument-arena:0.1.0'
terraform -chdir=infra apply \
  -var='image=ghcr.io/kianbahasadri/argument-arena:0.1.0'
```

The default kubeconfig path is `~/.kube/config`; set `-var="kubeconfig_path=$KUBECONFIG"` if your environment points elsewhere. Keep kubeconfig, state, plans, and tfvars private and outside Git. Namespace and resources created with kubectl require Terraform imports before adopting them. After Terraform creates the namespace, create `bot-credentials` as above; Terraform intentionally does not manage its contents.

## Update, rollback, and credentials

Publish a new immutable image version and update the rendered manifest or Terraform `image` input. Recreate strategy stops the previous client before starting the next. SQLite also has a process lock, and database transactions retain state across restarts.

With kubectl-managed resources, an emergency rollback is:

```bash
kubectl -n argument-arena rollout undo deployment/bot
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
```

Record the rolled-back image in your declarative configuration. With Terraform, set the previous image and apply the reviewed plan. Back up the database before any future incompatible schema migration.

To rotate credentials, edit the private environment file and update the existing Secret through a pipe, then restart. The generated Secret goes directly to kubectl rather than terminal output:

```bash
kubectl -n argument-arena create secret generic bot-credentials \
  --from-env-file="$arena_credentials" --dry-run=client -o yaml \
  | kubectl -n argument-arena apply -f -
kubectl -n argument-arena rollout restart deployment/bot
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
```

Do not delete the namespace or PVC to rotate keys. Keep secret values out of terminal output and shell history.

## Back up and restore

Run SQLite's online backup inside the running container, then copy the resulting file to private storage outside the worker:

```bash
kubectl -n argument-arena exec deployment/bot -- python -c \
  "import sqlite3; s=sqlite3.connect('/data/arena.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d); d.close(); s.close()"
umask 077
arena_backup=$(mktemp "$HOME/.local/state/argument-arena/backup-XXXXXXXX.sqlite3.partial")
if kubectl -n argument-arena exec deployment/bot -- cat /data/backup.sqlite3 > "$arena_backup"; then
  python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'; c.close()" "$arena_backup" \
    && mv "$arena_backup" "${arena_backup%.partial}"
fi
```

The unique filename preserves earlier backups if the copy or integrity check fails. Files retaining `.partial` are incomplete/unverified. For a local database use `python scripts/backup.py data/arena.sqlite3 /private/path/backup.sqlite3`. Protect and periodically move backups off the laptop. SQLite's journal files are not independent backups.

To restore, stop the deployment, restore a verified backup to the worker's backing directory as `arena.sqlite3` owned by UID/GID 10001, remove obsolete `arena.sqlite3-wal` and `arena.sqlite3-shm` only while no client is using them, then start the deployment. Keep the original directory until the restore is verified. The PV's Retain policy preserves data when its claim is removed, but does not itself provide a backup.
