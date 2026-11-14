# Deployment on Guaranine

This target runs the same `argument-arena` package and image as the [Docker deployment](deployment.md), with one Discord Gateway client and a retained SQLite volume. It needs outbound DNS and public HTTPS/WSS, with no Service, Ingress or public port. Publishing an image, creating credentials and applying cluster resources remain operator steps.

## Prepare and build

Connect to Tailscale and use Guaranine's operator kubeconfig outside this repository. Verify the worker and its architecture:

```bash
export KUBECONFIG="${GUARANINE_OPERATOR_DIR:-$HOME/.local/state/guaranine-kairos}/kubeconfig"
kubectl get nodes -L kubernetes.io/arch
bash scripts/setup-dev.sh
source .venv/bin/activate
bash scripts/validate.sh
```

The infrastructure defaults to worker `demure`. Select the actual Ready worker and build for its architecture. For an amd64 worker:

```bash
docker buildx build --platform linux/amd64 --load \
  -t ghcr.io/kianbahasadri/argument-arena:0.2.0 .
docker login ghcr.io
docker push ghcr.io/kianbahasadri/argument-arena:0.2.0
```

Prefer the pushed image digest for the deployment. A public GHCR package needs no pull secret; private packages require a `kubernetes.io/dockerconfigjson` Secret named by `--pull-secret` or Terraform's `pull_secret`. Keep registry credentials outside Git.

Follow [Discord installation](getting-started.md) to enable Message Content Intent and install the bot with Administrator permission. Copy the server ID for the required `--guild-id` argument. LLM assistance uses an OpenAI-compatible provider; research uses Brave Search and independently retrieved HTTPS pages. Missing provider files produce an unavailable assessment without preventing match management.

## Prepare local storage and credentials

Guaranine has no default storage provisioner. The retained local PersistentVolume is pinned to one worker. Create its backing directory on that worker using existing administrative access:

```bash
sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/argument-arena
```

Confirm that `/var/lib` persists on the Kairos worker. The database stays on that laptop when it disconnects; the bot resumes there and conservatively extends response clocks after downtime. Run one replica per database.

Create the namespace, then prepare private UTF-8 files containing only the relevant token/key, without shell assignments:

```bash
kubectl create namespace argument-arena
umask 077
arena_secrets="$HOME/.local/state/argument-arena/secrets"
mkdir -p "$arena_secrets"
${EDITOR:-nano} "$arena_secrets/discord-token"
kubectl -n argument-arena create secret generic bot-credentials \
  --from-file="discord-token=$arena_secrets/discord-token"
```

For AI features, create `llm-key` and `search-key` in the same private directory. Recreate the Secret using all available files and pipe it straight to kubectl:

```bash
kubectl -n argument-arena create secret generic bot-credentials \
  --from-file="discord-token=$arena_secrets/discord-token" \
  --from-file="llm-key=$arena_secrets/llm-key" \
  --from-file="search-key=$arena_secrets/search-key" \
  --dry-run=client -o yaml | kubectl apply -f -
```

The deployment mounts this Secret read-only at `/run/secrets`. UID/GID 10001 reads the files using the pod's filesystem group. Secret values never enter the rendered manifest or Terraform state. Guaranine encrypts Kubernetes Secrets at rest.

## Deploy with kubectl

Choose this workflow or Terraform below as the manager for these resources. Substitute the intended server ID and published image:

```bash
python scripts/render_manifests.py \
  --image ghcr.io/kianbahasadri/argument-arena:0.2.0 \
  --guild-id 123456789012345678 \
  --worker-name demure > /tmp/argument-arena.yaml
kubectl apply --dry-run=server -f /tmp/argument-arena.yaml
kubectl apply -f /tmp/argument-arena.yaml
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
kubectl -n argument-arena get pods,pvc
kubectl -n argument-arena logs deployment/bot --tail=100
```

For a private image add `--pull-secret ghcr-pull` after creating that registry Secret in the namespace. Use `--llm-model` and `--llm-endpoint` to select another compatible model/provider. Startup and liveness use `argument-arena healthcheck --liveness`; readiness uses `argument-arena healthcheck` and waits for Discord readiness.

Run `/diagnostic` in Discord, create the four match categories, and run `/setup`. Start a casual match with research and judging disabled for the initial infrastructure check, then deliberately verify configured AI features. See [commands](commands.md).

## Terraform alternative

`infra/` renders the same Kubernetes template. It manages the namespace, PV, PVC, Deployment and NetworkPolicies on the existing cluster, and protects the namespace against destruction. `infra/terraform/` is the separate Docker-daemon target.

```bash
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan \
  -var="kubeconfig_path=$KUBECONFIG" \
  -var='guild_id=123456789012345678' \
  -var='image=ghcr.io/kianbahasadri/argument-arena:0.2.0'
```

Review the plan before applying the same inputs. Let Terraform create the namespace first, then create `bot-credentials` and any registry Secret; Terraform does not manage secret contents. A namespace or other resources already created with kubectl require imports before Terraform adoption. Keep kubeconfig, state, plans and tfvars private and outside Git.

## Updates, credentials and recovery

Back up before upgrading the image. Update the manifest or Terraform input to an immutable new image. The Recreate strategy stops the old client first, and the runtime also holds a process lock. For an emergency kubectl rollback use `kubectl -n argument-arena rollout undo deployment/bot`, then record the chosen image in the declarative configuration. A schema downgrade requires a compatible pre-upgrade snapshot; see [migration and backup contracts](architecture.md).

Rotate mounted credential files by updating the Secret as above and running `kubectl -n argument-arena rollout restart deployment/bot`. Do not delete the namespace or PVC to rotate keys.

The installed `argument-arena backup` and `restore` commands require the bot to be stopped and hold its process lock. Scale the deployment to zero and wait for its pod to terminate before maintenance. Use a temporary maintenance pod running the same image as UID/GID 10001, mounting PVC `data` at `/var/lib/argument-arena` and following the same restricted security context. Run `argument-arena backup /var/lib/argument-arena/backup.sqlite3`, and copy the verified snapshot to private storage outside the worker. Use a unique destination for each snapshot. For restore, run `argument-arena restore /var/lib/argument-arena/backup.sqlite3` in that maintenance pod; the CLI validates schema/integrity and stages replacement atomically. Delete the maintenance pod before scaling the deployment back to one. Keep the original backup until verification completes.

The PV's Retain policy preserves data after claim removal; it does not provide a backup. Never copy only the open `arena.sqlite3` file or remove its WAL/SHM files while any process uses the database.
