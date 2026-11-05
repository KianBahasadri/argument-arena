#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
terraform_binary="$("$PYTHON" scripts/ensure-terraform.py)"
export PATH="$(dirname -- "$terraform_binary"):$PATH"
# The worker may invoke this entry point after installing only requirements-dev.txt.
"$PYTHON" -m pip install --no-deps --no-build-isolation --editable .
"$PYTHON" -m pip check
"$PYTHON" -m ruff check src tests scripts
"$PYTHON" -m ruff format --check src tests scripts
"$PYTHON" -m pytest
"$PYTHON" -m pymarkdown --config .pymarkdown.json scan --recurse --respect-gitignore .

# Use an isolated copy so local tfvars, state and backends can never affect validation.
validation_dir="$(mktemp -d)"
trap 'rm -rf -- "$validation_dir"' EXIT
cp infra/terraform/*.tf infra/terraform/.terraform.lock.hcl "$validation_dir/"
cp -R infra/terraform/tests "$validation_dir/"
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir="$validation_dir" init -backend=false -input=false -lockfile=readonly -no-color
terraform -chdir="$validation_dir" validate -no-color
terraform -chdir="$validation_dir" test -no-color
"$PYTHON" -m build --no-isolation --outdir "$validation_dir/dist"
"$PYTHON" scripts/check-container.py
