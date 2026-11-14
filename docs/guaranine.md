# Deployment on Guaranine

This target runs the same `argument-arena` package and image as the [Docker deployment](deployment.md), with one Discord Gateway client and a retained SQLite volume. It needs outbound DNS and public HTTPS/WSS, with no Service, Ingress or public port. GitHub Actions publishes the image after validation on main. Creating credentials and applying cluster resources remain operator steps.

## Prepare and choose an image

Connect to Tailscale. Guaranine's operator kubeconfig is already available through `~/.kube/config`; use plain kubectl. Verify the worker and its architecture:

```bash
kubectl get nodes -L kubernetes.io/arch
```

The infrastructure defaults to worker `demure`. Select the actual Ready worker. The published image targets `linux/amd64`; another worker architecture needs a corresponding build.

### Automatic image publication

The [Clusterfork repository validation workflow](https://github.com/KianBahasadri/argument-arena/actions/workflows/clusterfork-validation.yml) runs the existing **Clusterfork validation** check first. After it succeeds for a commit on main, **Publish container image** builds the Dockerfile and uploads `ghcr.io/kianbahasadri/argument-arena:sha-COMMIT`, where `COMMIT` is the full Git commit ID. Other branches and pull requests only validate. The publisher authenticates with the built-in `GITHUB_TOKEN`, uses OCI source metadata to link the package to this repository, and then pulls the published digest and runs the installed CLI without network access. No registry token or cluster credentials need to be added as repository secrets.

To retry publication, open that workflow in GitHub, choose **Run workflow**, select **main**, and run it. This reruns validation before publishing. The equivalent GitHub CLI commands are:

```bash
gh workflow run clusterfork-validation.yml --ref main
gh run list --workflow clusterfork-validation.yml --branch main --limit 5
```

Open the successful run's summary and copy the full **Deploy this digest** reference. Set it locally for the deployment commands below, replacing the example suffix with that run's actual SHA-256 digest:

```bash
arena_image='ghcr.io/kianbahasadri/argument-arena@sha256:REPLACE_WITH_DIGEST'
```

The digest identifies the published image exactly, including when a workflow is rerun. Publishing does not change the running bot; choose and deploy the desired digest explicitly.

### Package access

GHCR packages start private, even for a public source repository. For anonymous cluster pulls, open the [Argument Arena package](https://github.com/users/KianBahasadri/packages/container/package/argument-arena), choose **Package settings**, and change its visibility to **Public**. A public package needs no pull secret. If keeping it private, create a `kubernetes.io/dockerconfigjson` Secret and pass its name with `--pull-secret` or Terraform's `pull_secret`. Keep registry credentials outside Git.

If the package was initially uploaded manually, check its settings to ensure it is linked to `KianBahasadri/argument-arena` and grants that repository's Actions write access. The publisher's OCI source label establishes this link for new packages. See [GitHub's registry authentication and package access documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Follow [Discord installation](getting-started.md) to enable Message Content Intent and install the bot with Administrator permission. Copy the server ID for the required `--guild-id` argument. LLM assistance uses an OpenAI-compatible provider; research uses Brave Search and independently retrieved HTTPS pages. Missing provider files produce an unavailable assessment without preventing match management.

## Check storage and prepare credentials

Guaranine's OpenEBS provisioner creates storage automatically when the bot uses its PVC. Check that the provisioner is ready and the `openebs-hostpath` StorageClass uses `Retain` and `WaitForFirstConsumer`:

```bash
kubectl -n openebs rollout status deployment/openebs-localpv
kubectl get storageclass openebs-hostpath
```

The app requests a 1Gi volume from that class. OpenEBS creates its directory under `/usr/local/openebs/local` on the selected worker's persistent Kairos disk; the pod's filesystem group gives UID/GID 10001 write access. No per-app SSH or directory preparation is required. The container mounts the volume at `/var/lib/argument-arena`. A claim stays Pending until its consumer is scheduled. Once bound, the database stays on that laptop when it disconnects; the bot resumes there and conservatively extends response clocks after downtime. Requested capacity is not a disk quota or a backup. Run one replica per database.

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

Choose this workflow or Terraform below as the manager for these resources. Set `arena_image` to the published digest above and substitute the intended server ID:

```bash
python scripts/render_manifests.py \
  --image "$arena_image" \
  --guild-id 123456789012345678 > /tmp/argument-arena.yaml
kubectl apply --dry-run=server -f /tmp/argument-arena.yaml
kubectl apply -f /tmp/argument-arena.yaml
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
kubectl -n argument-arena get pods,pvc
kubectl -n argument-arena logs deployment/bot --tail=100
```

For a private image add `--pull-secret ghcr-pull` after creating that registry Secret in the namespace. Use `--llm-model` and `--llm-endpoint` to select another compatible model/provider. Startup and liveness use `argument-arena healthcheck --liveness`; readiness uses `argument-arena healthcheck` and waits for Discord readiness.

Run `/diagnostic` in Discord, create the four match categories, and run `/setup`. Start a casual match with research and judging disabled for the initial infrastructure check, then deliberately verify configured AI features. See [commands](commands.md).

## Terraform alternative

`infra/` renders the same Kubernetes template. It manages the namespace, PVC, Deployment and NetworkPolicies on the existing cluster, and protects the namespace against destruction. OpenEBS manages the resulting PV and worker placement. `infra/terraform/` is the separate Docker-daemon target.

```bash
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan \
  -var='guild_id=123456789012345678' \
  -var="image=$arena_image"
```

Review the plan before applying the same inputs. Let Terraform create the namespace first, then create `bot-credentials` and any registry Secret; Terraform does not manage secret contents. A namespace or other resources already created with kubectl require imports before Terraform adoption. Keep kubeconfig, state, plans and tfvars private and outside Git.

## Updates, credentials and recovery

Back up before upgrading the image. Update the manifest or Terraform input to an immutable new image. The Recreate strategy stops the old client first, and the runtime also holds a process lock. For an emergency kubectl rollback use `kubectl -n argument-arena rollout undo deployment/bot`, then record the chosen image in the declarative configuration. A schema downgrade requires a compatible pre-upgrade snapshot; see [migration and backup contracts](architecture.md).

Rotate mounted credential files by updating the Secret as above and running `kubectl -n argument-arena rollout restart deployment/bot`. Do not delete the namespace or PVC to rotate keys.

The installed `argument-arena backup` and `restore` commands require the bot to be stopped and hold its process lock. Scale the deployment to zero and wait for its pod to terminate before maintenance. Use a temporary maintenance pod running the same image as UID/GID 10001, mounting PVC `data` at `/var/lib/argument-arena` and following the same restricted security context. Run `argument-arena backup /var/lib/argument-arena/backup.sqlite3`, and copy the verified snapshot to private storage outside the worker. Use a unique destination for each snapshot. For restore, run `argument-arena restore /var/lib/argument-arena/backup.sqlite3` in that maintenance pod; the CLI validates schema/integrity and stages replacement atomically. Delete the maintenance pod before scaling the deployment back to one. Keep the original backup until verification completes.

The StorageClass's Retain policy preserves data after claim removal; it does not provide a backup. Never copy only the open `arena.sqlite3` file or remove its WAL/SHM files while any process uses the database. Existing installations with a manually bound static volume require an explicit backup and data migration before adopting this PVC configuration; do not replace or delete an existing claim to update the deployment.
