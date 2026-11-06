#!/usr/bin/env python3
"""Build and exercise the installed image without a token, network, or server apply."""

import json
import subprocess
import uuid


def call(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture, timeout=300)
    return result.stdout if capture else ""


def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    image, volume = f"argument-arena-validation:{suffix}", f"argument-arena-validation-{suffix}"
    try:
        call("docker", "build", "--tag", image, ".")
        config = json.loads(call("docker", "image", "inspect", image, capture=True))[0]["Config"]
        assert config["User"] == "10001:10001"
        assert config["Entrypoint"] == ["argument-arena"]
        assert config["Healthcheck"]["Test"] == ["CMD", "argument-arena", "healthcheck"]
        call("docker", "volume", "create", volume, capture=True)
        options = (
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--mount",
            f"type=volume,source={volume},target=/var/lib/argument-arena",
        )
        call(*options, image, "migrate")
        # Two separate containers prove that package imports, volume ownership, writes,
        # migrations and persisted settings work with the actual non-root image.
        program = """
import asyncio
from pathlib import Path
from argument_arena.storage import Storage
async def exercise():
    async with Storage(Path('/var/lib/argument-arena/arena.sqlite3')) as db:
        previous = await db.get('validation', 'value', 0)
        await db.put('validation', 'value', previous + 1)
        assert await db.get('validation', 'value') == previous + 1
asyncio.run(exercise())
"""
        for _ in range(2):
            call(*options, "--entrypoint", "python", image, "-c", program)
        backup = "/var/lib/argument-arena/backup.sqlite3"
        call(*options, image, "backup", backup)
        call(*options, "--entrypoint", "python", image, "-c", program)
        call(*options, image, "restore", backup)
        verify = """
import asyncio
from pathlib import Path
from argument_arena.storage import Storage
async def check():
    async with Storage(Path('/var/lib/argument-arena/arena.sqlite3')) as db:
        assert await db.get('validation', 'value') == 2
asyncio.run(check())
"""
        call(*options, "--entrypoint", "python", image, "-c", verify)
        # Probe behavior is local and does not read Discord configuration.
        probe = subprocess.run([*options, image, "healthcheck"], check=False, timeout=30)
        assert probe.returncode == 1
        print("Container build, non-root persistence, backup and restore passed")
    finally:
        subprocess.run(
            ["docker", "volume", "rm", volume], check=False, capture_output=True, timeout=30
        )
        subprocess.run(
            ["docker", "image", "rm", image], check=False, capture_output=True, timeout=30
        )


if __name__ == "__main__":
    main()
