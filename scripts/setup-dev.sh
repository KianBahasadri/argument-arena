#!/usr/bin/env bash
# Python 3.12 and a local Docker daemon are prerequisites; validation bootstraps Terraform.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --requirement requirements-dev.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation --editable .

.venv/bin/python -m pip check
