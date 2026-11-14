#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export CUSTOM_COMPILE_COMMAND='bash scripts/lock-dependencies.sh'
python3 -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements.txt pyproject.toml
python3 -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --constraint requirements.txt --extra dev --output-file requirements-dev.txt pyproject.toml
python3 -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file requirements-build.txt requirements-build.in
