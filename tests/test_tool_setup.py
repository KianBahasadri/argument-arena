import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "ensure_terraform", Path(__file__).resolve().parents[1] / "scripts/ensure-terraform.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def release_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("terraform", b"offline Terraform fixture")
    return output.getvalue()


def test_missing_cli_installs_verified_release_and_reuses_cache(tmp_path, monkeypatch):
    release = release_archive()
    checksum = hashlib.sha256(release).hexdigest()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "terraform-checksums.json").write_text(
        json.dumps({"version": "1.13.5", "archives": {"linux_amd64": checksum}})
    )
    (tmp_path / ".terraform-version").write_text("1.13.5\n")
    download = Mock(side_effect=lambda *_args, **_kwargs: io.BytesIO(release))
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    monkeypatch.setattr(setup, "platform_key", lambda: "linux_amd64")
    monkeypatch.setattr(setup.urllib.request, "urlopen", download)
    monkeypatch.setattr(
        setup,
        "matches_version",
        lambda path, _version: path.read_bytes() == b"offline Terraform fixture",
    )
    executable = setup.ensure()
    assert executable.read_bytes() == b"offline Terraform fixture"
    assert setup.ensure() == executable
    download.assert_called_once_with(
        "https://releases.hashicorp.com/terraform/1.13.5/terraform_1.13.5_linux_amd64.zip",
        timeout=30,
    )


def test_checksum_mismatch_rejects_download_before_execution(tmp_path, monkeypatch):
    download = Mock(return_value=io.BytesIO(release_archive()))
    execute = Mock()
    monkeypatch.setattr(setup.urllib.request, "urlopen", download)
    monkeypatch.setattr(setup, "matches_version", execute)
    with pytest.raises(setup.ToolSetupError, match="checksum"):
        setup.install("1.13.5", "linux_amd64", "0" * 64, tmp_path)
    execute.assert_not_called()
    assert not (tmp_path / "terraform").exists()
    assert list(tmp_path.iterdir()) == []


def test_version_mismatch_rejects_download_before_publication(tmp_path, monkeypatch):
    release = release_archive()
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(release))
    monkeypatch.setattr(setup, "matches_version", lambda *_: False)
    with pytest.raises(setup.ToolSetupError, match="pinned version"):
        setup.install("1.13.5", "linux_amd64", hashlib.sha256(release).hexdigest(), tmp_path)
    assert not (tmp_path / "terraform").exists()


@pytest.mark.parametrize("reported,expected", [("1.13.5", True), ("1.12.0", False)])
def test_existing_cli_must_report_pinned_version(monkeypatch, reported, expected):
    result = Mock(stdout=json.dumps({"terraform_version": reported}))
    monkeypatch.setattr(setup.subprocess, "run", Mock(return_value=result))
    assert setup.matches_version(Path("terraform"), "1.13.5") is expected
