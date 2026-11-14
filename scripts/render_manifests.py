#!/usr/bin/env python3
"""Render the same resources Terraform uses for operators who prefer kubectl."""

import argparse
import re
import sys
from pathlib import Path


def render(
    image,
    guild_id,
    pull_secret="",
    llm_model="gpt-4.1-mini",
    llm_endpoint="https://api.openai.com/v1/chat/completions",
):
    pattern = (
        r"(?:[A-Za-z0-9._:-]+/)*[A-Za-z0-9._-]+"
        r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]*|@sha256:[a-f0-9]{64})"
    )
    if not re.fullmatch(pattern, image) or image.endswith(":latest"):
        raise ValueError("Provide a versioned image tag or digest.")
    if pull_secret and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", pull_secret):
        raise ValueError("Invalid registry Secret name.")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", guild_id) or not int(guild_id) < 2**64:
        raise ValueError("Use a positive unsigned 64-bit Discord server ID.")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", llm_model):
        raise ValueError("Invalid model identifier.")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::443)?/[A-Za-z0-9_./-]+", llm_endpoint):
        raise ValueError("Use an HTTPS API URL without credentials, query parameters or fragments.")
    source = Path(__file__).resolve().parents[1] / "infra/resources.yaml.tftpl"
    template = source.read_text()
    template = re.sub(
        r'%\{ if pull_secret != "" ~\}\n(.*?)%\{ endif ~\}\n',
        lambda match: match[1] if pull_secret else "",
        template,
        flags=re.DOTALL,
    )
    for key, value in {
        "image": image,
        "guild_id": guild_id,
        "pull_secret": pull_secret,
        "llm_model": llm_model,
        "llm_endpoint": llm_endpoint,
    }.items():
        template = template.replace("${" + key + "}", value)
    if "${" in template or "%{" in template:
        raise ValueError("An infrastructure template variable was not rendered.")
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--guild-id", required=True)
    parser.add_argument("--pull-secret", default="")
    parser.add_argument("--llm-model", default="gpt-4.1-mini")
    parser.add_argument("--llm-endpoint", default="https://api.openai.com/v1/chat/completions")
    args = parser.parse_args()
    try:
        sys.stdout.write(render(**vars(args)))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
