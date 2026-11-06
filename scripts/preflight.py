#!/usr/bin/env python3
"""Validate deployment inputs offline, or explicitly inspect the selected daemon."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

REQUIRED = {
    "server_os",
    "server_identity",
    "docker_host",
    "platform",
    "image",
    "secrets_host_path",
    "guild_id",
}


class PreflightError(ValueError):
    pass


def validate(values: dict[str, Any]) -> None:
    if set(values) - REQUIRED - {"name", "sync_commands"}:
        raise PreflightError("Unknown variables; secret values must never be passed to Terraform")
    for key in sorted(REQUIRED):
        if not isinstance(values.get(key), str) or not values[key].strip():
            raise PreflightError(
                f"Supply {key}; server inputs are intentionally blank in the example"
            )
    endpoint = values["docker_host"]
    if not re.fullmatch(
        r"(?:unix:///\S+|npipe:////\S+|ssh://[A-Za-z0-9_.-]+@"
        r"(?:[A-Za-z0-9_.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?)",
        endpoint,
    ):
        raise PreflightError("docker_host must be an explicit local socket or SSH endpoint")
    if values["platform"] not in {"linux/amd64", "linux/arm64"}:
        raise PreflightError("Select the server's linux/amd64 or linux/arm64 container platform")
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", values["image"]):
        raise PreflightError("image must be pinned to a registry manifest digest")
    if not re.fullmatch(r"/[^\n\r,]+", values["secrets_host_path"]):
        raise PreflightError(
            "secrets_host_path must be a dedicated absolute runtime-host directory"
        )
    if not re.fullmatch(r"[1-9][0-9]{0,19}", values["guild_id"]) or not (
        int(values["guild_id"]) < 2**64
    ):
        raise PreflightError("guild_id must be an unsigned 64-bit snowflake string")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", values.get("name", "argument-arena")):
        raise PreflightError("name must be a stable lowercase installation name")
    if not isinstance(values.get("sync_commands", True), bool):
        raise PreflightError("sync_commands must be a boolean")


def docker(values: dict[str, Any], *args: str) -> str:
    env = os.environ.copy()
    # An ambient context must not redirect checks away from the reviewed explicit endpoint.
    env.pop("DOCKER_CONTEXT", None)
    result = subprocess.run(
        ["docker", "--host", values["docker_host"], *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        # Docker/SSH error output can include host details, credentials or image metadata.
        raise PreflightError(
            "Docker preflight failed; inspect endpoint/access/image setup privately"
        )
    return result.stdout


def live_checks(values: dict[str, Any]) -> None:
    info = json.loads(docker(values, "info", "--format", "{{json .}}"))
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
        info["Architecture"], info["Architecture"]
    )
    if info["Name"] != values["server_identity"]:
        raise PreflightError("Docker daemon identity differs from server_identity")
    if f"{info['OSType']}/{architecture}" != values["platform"]:
        raise PreflightError("Docker runtime platform differs from the selected platform")
    # The operator must pull/load the digest first, using external registry authentication.
    image = json.loads(
        docker(values, "image", "inspect", values["image"], "--format", "{{json .}}")
    )
    if f"{image['Os']}/{image['Architecture']}" != values["platform"]:
        raise PreflightError("Loaded image does not match the selected platform")
    # A throwaway, isolated non-root container verifies mounts/config without a Discord request.
    # No token bytes are printed, uploaded, or made available to Terraform.
    docker(
        values,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=10001:10001",
        "--mount",
        f"type=bind,src={values['secrets_host_path']},dst=/run/secrets,readonly",
        "--env",
        f"AA_GUILD_ID={values['guild_id']}",
        values["image"],
        "check-config",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vars", type=Path, required=True, help="Private terraform.tfvars.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--offline", action="store_true", help="Validate inputs only; never contact Docker"
    )
    mode.add_argument(
        "--live", action="store_true", help="Inspect selected daemon and mounted config"
    )
    args = parser.parse_args()
    try:
        values = json.loads(args.vars.read_text(encoding="utf-8"))
        if os.environ.get("DOCKER_CONTEXT"):
            raise PreflightError("Unset DOCKER_CONTEXT before preflight and Terraform operations")
        if not isinstance(values, dict):
            raise PreflightError("Variable file must be a JSON object")
        validate(values)
        if args.live:
            live_checks(values)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, PreflightError) else type(error).__name__
        print(f"Preflight failed: {message}")
        return 1
    print("Preflight passed" + (" (inputs only; server not contacted)" if args.offline else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
