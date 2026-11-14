#!/usr/bin/env python3
"""Render the same resources Terraform uses for operators who prefer kubectl."""

import argparse
from pathlib import Path
import re
import sys


def render(image, worker_name="demure", storage_path="/var/lib/argument-arena", pull_secret=""):
    pattern = r"(?:[A-Za-z0-9._:-]+/)*[A-Za-z0-9._-]+(?::[A-Za-z0-9_][A-Za-z0-9_.-]*|@sha256:[a-f0-9]{64})"
    if not re.fullmatch(pattern, image) or image.endswith(":latest"):
        raise ValueError("Provide a versioned image tag or digest.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", worker_name):
        raise ValueError("Invalid worker name.")
    if not re.fullmatch(r"/var/[A-Za-z0-9/_-]+", storage_path):
        raise ValueError("Use a persistent absolute directory under /var.")
    if pull_secret and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", pull_secret):
        raise ValueError("Invalid registry Secret name.")
    source = Path(__file__).resolve().parents[1] / "infra/resources.yaml.tftpl"
    template = source.read_text()
    template = re.sub(r'%\{ if pull_secret != "" ~\}\n(.*?)%\{ endif ~\}\n',
                      lambda match: match[1] if pull_secret else "", template, flags=re.DOTALL)
    for key, value in {"image": image, "worker_name": worker_name,
                       "storage_path": storage_path, "pull_secret": pull_secret}.items():
        template = template.replace("${" + key + "}", value)
    if "${" in template or "%{" in template:
        raise ValueError("An infrastructure template variable was not rendered.")
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--worker-name", default="demure")
    parser.add_argument("--storage-path", default="/var/lib/argument-arena")
    parser.add_argument("--pull-secret", default="")
    args = parser.parse_args()
    try:
        sys.stdout.write(render(**vars(args)))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
