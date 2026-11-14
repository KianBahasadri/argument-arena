#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -m pymarkdown --config .pymarkdown.json scan --recurse --respect-gitignore .
python3 -m ruff check arena tests scripts
python3 -m unittest discover -s tests -v
python3 -m compileall -q arena
