#!/usr/bin/env python3
"""Locate the pinned Terraform CLI or install a checksum-verified workspace copy."""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ToolSetupError(RuntimeError):
    pass


def matches_version(executable: Path, version: str) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "version", "-json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return json.loads(result.stdout)["terraform_version"] == version
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def platform_key() -> str:
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(platform.system())
    machine = platform.machine().lower()
    architecture = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine
    )
    if system is None or architecture is None:
        raise ToolSetupError("No pinned Terraform CLI for this development platform")
    return f"{system}_{architecture}"


def install(version: str, target: str, checksum: str, cache: Path) -> Path:
    executable = cache / ("terraform.exe" if target.startswith("windows_") else "terraform")
    if executable.is_file() and matches_version(executable, version):
        return executable
    cache.mkdir(parents=True, exist_ok=True)
    archive_name = f"terraform_{version}_{target}.zip"
    url = f"https://releases.hashicorp.com/terraform/{version}/{archive_name}"
    print(f"Installing checksum-verified Terraform {version} for {target}", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        archive_path = Path(directory) / archive_name
        with urllib.request.urlopen(url, timeout=30) as response, archive_path.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive_path.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != checksum:
            raise ToolSetupError("Terraform release checksum differs from the committed pin")
        staged = Path(directory) / executable.name
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(executable.name) as source, staged.open("wb") as output:
                shutil.copyfileobj(source, output)
        staged.chmod(0o755)
        if not matches_version(staged, version):
            raise ToolSetupError("Downloaded Terraform CLI does not report the pinned version")
        staged.replace(executable)
    return executable


def ensure() -> Path:
    version = (ROOT / ".terraform-version").read_text(encoding="utf-8").strip()
    lock = json.loads((ROOT / "scripts/terraform-checksums.json").read_text(encoding="utf-8"))
    if lock["version"] != version:
        raise ToolSetupError("Update Terraform release checksums together with .terraform-version")
    existing = shutil.which("terraform")
    if existing and matches_version(Path(existing), version):
        return Path(existing).resolve()
    target = platform_key()
    if target not in lock["archives"]:
        raise ToolSetupError("No pinned Terraform archive for this development platform")
    return install(
        version, target, lock["archives"][target], ROOT / ".tools/terraform" / version / target
    )


if __name__ == "__main__":
    try:
        print(ensure())
    except (OSError, ValueError, KeyError, ToolSetupError, zipfile.BadZipFile) as error:
        print(f"Terraform setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
