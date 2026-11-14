# Deployment on Guaranine

This target runs the same `argument-arena` package and image as the [Docker deployment](deployment.md), with one Discord Gateway client and a retained SQLite volume. It needs outbound DNS and public HTTPS/WSS, with no Service, Ingress or public port. GitHub Actions publishes the image after validation on main. Terraform in `infra/` manages the namespace, credentials Secret, storage claim, Deployment and NetworkPolicies. The operator reviews and applies its plan.

## Prepare and choose an image

Connect to Tailscale. Guaranine's operator kubeconfig is already available through `~/.kube/config`; use plain kubectl. Verify the worker and its architecture:

```bash
kubectl get nodes -L kubernetes.io/arch
```

Kubernetes selects an available worker when provisioning the bot's volume. The published image targets `linux/amd64`; another worker architecture needs a corresponding build.

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

Follow [Discord installation](getting-started.md) to enable Message Content Intent and install the bot with Administrator permission. Copy the server ID for the required `guild_id` input. LLM assistance uses an OpenAI-compatible provider; research uses Brave Search and independently retrieved HTTPS pages. Missing provider files produce an unavailable assessment without preventing match management.

## Check storage and prepare credentials

Guaranine's OpenEBS provisioner creates storage automatically when the bot uses its PVC. Check that the provisioner is ready and the `openebs-hostpath` StorageClass uses `Retain` and `WaitForFirstConsumer`:

```bash
kubectl -n openebs rollout status deployment/openebs-localpv
kubectl get storageclass openebs-hostpath
```

The app requests a 1Gi volume from that class. OpenEBS creates its directory under `/usr/local/openebs/local` on the selected worker's persistent Kairos disk; the pod's filesystem group gives UID/GID 10001 write access. No per-app SSH or directory preparation is required. The container mounts the volume at `/var/lib/argument-arena`. A claim stays Pending until its consumer is scheduled. Once bound, the database stays on that laptop when it disconnects; the bot resumes there and conservatively extends response clocks after downtime. Requested capacity is not a disk quota or a backup. Run one replica per database.

From the repository root, prepare private UTF-8 files in the ignored `.secrets/` directory containing only the relevant token/key, without shell assignments:

```bash
umask 077
mkdir -p .secrets
${EDITOR:-nano} .secrets/discord-token
```

For AI features, create `llm-key` and `search-key` in the same private directory. Terraform includes those files when present. It creates the namespace first, then the Secret, then the remaining application resources. Do not create those resources manually before applying Terraform.

The deployment mounts this Secret read-only at `/run/secrets`. UID/GID 10001 reads the files using the pod's filesystem group. Terraform uses the provider's write-only `data_wo` field, keeping secret values out of saved plans and state; the pinned provider also skips reading them back into state. This requires Terraform 1.11 or newer; the repository pins 1.13.5. Secret values never enter the rendered application manifest. Guaranine encrypts Kubernetes Secrets at rest. See the [pinned provider implementation](https://github.com/hashicorp/terraform-provider-kubernetes/blob/v2.38.0/kubernetes/resource_kubernetes_secret_v1.go).

## Plan and deploy with Terraform

Create the ignored `infra/terraform.tfvars` file with the intended server ID and the published image digest. These inputs contain no credentials:

```hcl
guild_id = "123456789012345678"
image    = "ghcr.io/kianbahasadri/argument-arena@sha256:REPLACE_WITH_DIGEST"
```

Initialize with the repository's pinned CLI, validate the configuration, and save a plan:

```bash
umask 077
arena_tf="$(python3 scripts/ensure-terraform.py)"
"$arena_tf" -chdir=infra init -lockfile=readonly
"$arena_tf" -chdir=infra validate
"$arena_tf" -chdir=infra plan -out=arena.tfplan
"$arena_tf" -chdir=infra show arena.tfplan
```

`init` installs the pinned provider and initializes local state; `plan` previews changes without applying them. Review the plan before applying it. For a fresh installation, it should create the application namespace, Secret, PVC, Deployment and two NetworkPolicies. OpenEBS creates the backing PV when the bot is scheduled.

Apply the reviewed plan, then inspect the rollout:

```bash
"$arena_tf" -chdir=infra apply arena.tfplan
kubectl -n argument-arena rollout status deployment/bot --timeout=180s
kubectl -n argument-arena get pods,pvc
kubectl -n argument-arena logs deployment/bot --tail=100
```

Use `llm_model` and `llm_endpoint` in the tfvars file to select another compatible model/provider. For a private image, `pull_secret` names an existing registry Secret. Startup and liveness use `argument-arena healthcheck --liveness`; readiness uses `argument-arena healthcheck` and waits for Discord readiness.

Run `/diagnostic` in Discord, create the four match categories, and run `/setup`. Start a casual match with research and judging disabled for the initial infrastructure check, then deliberately verify configured AI features. See [commands](commands.md).

The local state, saved plan and tfvars stay in the ignored files under `infra/`; protect them and back up state off the operator computer. Use one authoritative state and one operator at a time. Keep the cluster kubeconfig in its existing protected location. A namespace or other resources already created with kubectl require imports before Terraform adoption. `infra/terraform/` is the separate Docker-daemon target.

## Updates, credentials and recovery

Back up before upgrading the image. Update Terraform's `image` input to an immutable new image and review/apply a new plan. The Recreate strategy stops the old client first, and the runtime also holds a process lock. Roll back by restoring the intended digest in the Terraform input and applying a reviewed plan. A schema downgrade requires a compatible pre-upgrade snapshot; see [migration and backup contracts](architecture.md).

To add or rotate credentials, update the relevant files in `.secrets/`, increment `credentials_revision` in `infra/terraform.tfvars` (default 1), then review/apply a new plan. The revision causes Terraform to upload the write-only values and replace the bot pod with the updated Secret. Terraform cannot detect changes to write-only values without that revision. Do not delete the namespace or PVC to rotate keys.

The installed `argument-arena backup` and `restore` commands require the bot to be stopped and hold its process lock. Scale the deployment to zero and wait for its pod to terminate before maintenance. Use a temporary maintenance pod running the same image as UID/GID 10001, mounting PVC `data` at `/var/lib/argument-arena` and following the same restricted security context. Run `argument-arena backup /var/lib/argument-arena/backup.sqlite3`, and copy the verified snapshot to private storage outside the worker. Use a unique destination for each snapshot. For restore, run `argument-arena restore /var/lib/argument-arena/backup.sqlite3` in that maintenance pod; the CLI validates schema/integrity and stages replacement atomically. Delete the maintenance pod before scaling the deployment back to one. Keep the original backup until verification completes.

The StorageClass's Retain policy preserves data after claim removal; it does not provide a backup. Never copy only the open `arena.sqlite3` file or remove its WAL/SHM files while any process uses the database. Existing installations with a manually bound static volume require an explicit backup and data migration before adopting this PVC configuration; do not replace or delete an existing claim to update the deployment.
