# Development and offline validation

Use Python 3.12, Bash, and a local Docker daemon running Linux containers. The shared validation entry point uses Terraform **1.13.5** from `.terraform-version`: it reuses a matching CLI on PATH or downloads the [official release](https://releases.hashicorp.com/terraform/1.13.5/), verifies it against `scripts/terraform-checksums.json`, and caches the executable under ignored `.tools/terraform/`. Linux/macOS AMD64 and ARM64 and Windows AMD64 operator platforms have committed archive checksums. Docker must support the developer machine's architecture; the owner's server platform is a separate, intentionally blank deployment input.

```bash
bash scripts/setup-dev.sh
source .venv/bin/activate
bash scripts/validate.sh
```

The shared entry point bootstraps the pinned Terraform CLI and installs the local package in editable mode without dependency resolution or build isolation, so a worker invoking it after installing only `requirements-dev.txt` runs the same code. It then checks dependency consistency, Ruff lint/format, pytest, repository Markdown, Terraform formatting, initialization using the committed provider lock, validation, provider-mocked plan tests, Python sdist/wheel builds, and a real multi-stage container build. Container smoke checks use ephemeral named volumes, the actual installed package, the non-root user, a read-only root filesystem, and `--network=none` to test migrations, data across container replacements, backup, restore, and unready health behavior. Images/volumes created by the smoke script have unique names and are removed afterward.

Application tests replace Discord HTTP with a failing mock by default. They exercise configuration rejection, token loading, log redaction, client/command binding and permissions, reconnect/sync behavior, shutdown supervision, migrations and rollback/cancellation, durable settings, snapshot recovery, locks across processes, and preflight targeting. Terraform tests use the actual pinned provider schema with `mock_provider`; every run is a plan and never a live apply. The protected volume intentionally prevents destruction, including mocked-apply test cleanup. Validation copies only Terraform source/tests/lock into a temporary directory so private local tfvars and deployment state cannot influence it.

No Discord credentials, owner's server access, registry credentials, cloud credentials, or live Terraform apply are required. Dependency downloads, initial Terraform CLI setup, provider initialization, and container image pulls require public package/release/registry access on the first run. Subsequent application tests are offline. Validation never runs the bot's `run` command against Discord or the deployment's live preflight.

The existing GitHub Actions job retains the required name **Clusterfork validation** and runs the same entry point with Python 3.12 and the hosted runner's Docker daemon. CI installs the hash-locked Python dependencies, then the shared entry point sets up Terraform and the package exactly as it does in the worker. It has read-only repository permissions, no deployment job, and no secrets.

For a focused Python-only iteration, `python -m pytest` and `python -m ruff check src tests scripts` do not need Terraform or Docker. Run the complete entry point before delivery.

## Dependency updates

Inside the activated development environment, edit the direct pins in `pyproject.toml` (and `requirements-build.in` when build requirements change), then regenerate all locks:

```bash
bash scripts/lock-dependencies.sh
python -m pip install --require-hashes -r requirements-dev.txt
python -m pip install --no-deps --no-build-isolation -e .
bash scripts/validate.sh
```

The generator reuses existing transitive pins and constrains the development set to the runtime set. For an intentional transitive upgrade, use pip-tools' `--upgrade-package`/`--upgrade` while regenerating the runtime lock, then rerun the script. Review hashes and compatibility; do not hand-edit generated locks. Update the base tag/digest together in both Dockerfile stages when changing Python or OS library inputs. Never pass secrets into a build.

Provider updates change `infra/terraform/versions.tf`, followed by `terraform init -upgrade` and `terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64 -platform=windows_amd64` in that directory. Run formatting, schema validation, mocked tests, and the full shared entry point. Update `.terraform-version`, the Terraform version constraint, and the official release checksums in `scripts/terraform-checksums.json` together when changing the CLI version. Verify the checksum source before recording new pins.
