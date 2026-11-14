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
    llm_model="claude-haiku-5-5",
    llm_endpoint="https://opencode.ai/inference/go/openai/v1/chat/completions",
    credentials_revision=1,
    llm_judge_model="gemini-4-argon",
):
    pattern = (
        r"(?:[A-Za-z0-9._:-]+/)*[A-Za-z0-9._-]+"
        r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]*|@sha256:[a-f0-9]{64})"
    )
    if not re.fullmatch(pattern, image) or image.endswith(":latest"):
        raise ValueError("Provide a versioned image tag or digest.")
    if type(credentials_revision) is not int or credentials_revision < 1:
        raise ValueError("Use a positive integer credential revision.")
    if pull_secret and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", pull_secret):
        raise ValueError("Invalid registry Secret name.")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", guild_id) or not int(guild_id) < 2**64:
        raise ValueError("Use a positive unsigned 64-bit Discord server ID.")
    for model in (llm_model, llm_judge_model):
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", model):
            raise ValueError("Invalid model identifier.")
    if llm_endpoint not in {
        "https://opencode.ai/inference/go/openai/v1/chat/completions",
        "https://opencode.ai/inference/go/openai/v1/responses",
    }:
        raise ValueError("Use an OpenCode Go Chat Completions or Responses endpoint.")
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
        "llm_judge_model": llm_judge_model,
        "llm_endpoint": llm_endpoint,
        "credentials_revision": str(credentials_revision),
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
    parser.add_argument("--llm-model", default="claude-haiku-5-5")
    parser.add_argument("--llm-judge-model", default="gemini-4-argon")
    parser.add_argument(
        "--llm-endpoint", default="https://opencode.ai/inference/go/openai/v1/chat/completions"
    )
    parser.add_argument("--credentials-revision", type=int, default=1)
    args = parser.parse_args()
    try:
        sys.stdout.write(render(**vars(args)))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
