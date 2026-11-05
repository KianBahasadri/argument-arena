import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts/preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def values():
    return {
        "server_os": "operator selected OS",
        "server_identity": "offline-test.invalid",
        "docker_host": "ssh://operator@offline-test.invalid:22",
        "platform": "linux/amd64",
        "image": "example.invalid/arena@sha256:" + "a" * 64,
        "secrets_host_path": "/test/secrets",
        "guild_id": "123456789012345678",
    }


def test_blank_example_cannot_be_deployed():
    example = Path(__file__).resolve().parents[1] / "infra/terraform/terraform.tfvars.json.example"
    with pytest.raises(preflight.PreflightError):
        preflight.validate(json.loads(example.read_text()))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("docker_host", "tcp://example.invalid:2375"),
        ("docker_host", "ssh://user:password@example.invalid"),
        ("docker_host", "ssh://user@example.invalid?token=secret"),
        ("guild_id", str(2**64)),
        ("guild_id", "0"),
        ("image", "example.invalid/arena:latest"),
        ("platform", "windows/amd64"),
        ("secrets_host_path", "relative"),
        ("discord_token", "must not enter state"),
    ],
)
def test_invalid_inputs(values, key, value):
    with pytest.raises(preflight.PreflightError):
        preflight.validate(values | {key: value})


def test_live_checks_validate_identity_and_never_read_or_print_token(values, monkeypatch):
    docker = Mock(
        side_effect=[
            json.dumps(
                {"Name": values["server_identity"], "OSType": "linux", "Architecture": "x86_64"}
            ),
            json.dumps({"Os": "linux", "Architecture": "amd64"}),
            "",
        ]
    )
    monkeypatch.setattr(preflight, "docker", docker)
    preflight.validate(values)
    preflight.live_checks(values)
    invocation = docker.call_args.args
    assert "--network=none" in invocation
    assert "check-config" in invocation
    assert all("cat" != arg for arg in invocation)


def test_wrong_daemon_is_rejected_before_running_any_container(values, monkeypatch):
    docker = Mock(
        return_value=json.dumps(
            {"Name": "another-host.invalid", "OSType": "linux", "Architecture": "amd64"}
        )
    )
    monkeypatch.setattr(preflight, "docker", docker)
    with pytest.raises(preflight.PreflightError, match="identity"):
        preflight.live_checks(values)
    docker.assert_called_once()
