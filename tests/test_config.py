import json
import logging

import pytest

from argument_arena.cli import main
from argument_arena.config import Config, ConfigurationError
from argument_arena.logging import JsonFormatter, configure_logging


def environment(tmp_path):
    token = tmp_path / "token"
    token.write_text("offline-test-token\n")
    return {"AA_GUILD_ID": "123456789012345678", "AA_DISCORD_TOKEN_FILE": str(token)}


def test_config_defaults_and_file_only_secret(tmp_path):
    env = environment(tmp_path)
    config = Config.from_env(env)
    assert config.guild_id == 123456789012345678
    assert config.sync_commands
    assert config.read_token() == "offline-test-token"
    assert "offline-test-token" not in repr(config)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AA_GUILD_ID", ""),
        ("AA_GUILD_ID", "0"),
        ("AA_GUILD_ID", "-1"),
        ("AA_GUILD_ID", "1.1"),
        ("AA_GUILD_ID", "١"),
        ("AA_GUILD_ID", str(2**64)),
        ("AA_DISCORD_TOKEN_FILE", ""),
        ("AA_DATA_DIR", " "),
        ("AA_SYNC_COMMANDS", "yes"),
        ("AA_LOG_LEVEL", "verbose"),
    ],
)
def test_invalid_config_never_echoes_values(tmp_path, key, value):
    env = environment(tmp_path) | {key: value}
    with pytest.raises(ConfigurationError) as error:
        Config.from_env(env)
    assert key in str(error.value)


@pytest.mark.parametrize("token", ["", "two tokens", "a\nb", "a" * 4097, "\x80"])
def test_bad_token_file(tmp_path, token):
    env = environment(tmp_path)
    path = tmp_path / "token"
    path.write_bytes(token.encode() if token != "\x80" else b"\x80")
    with pytest.raises(ConfigurationError):
        Config.from_env(env).read_token()


def test_missing_token_and_config_check_are_offline(tmp_path, monkeypatch):
    env = environment(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main(["check-config"]) == 0
    (tmp_path / "token").unlink()
    assert main(["check-config"]) == 1


def test_json_logs_redact_token_urls_and_exception_contents():
    secret = "sensitive-test-token"
    error = ValueError(f"request included {secret} and other secret data")
    record = logging.LogRecord(
        "arena",
        logging.ERROR,
        "",
        0,
        f"failed {secret} https://discord.com/api/webhooks/id/interaction-token",
        (),
        (ValueError, error, None),
    )
    output = JsonFormatter((secret,)).format(record)
    payload = json.loads(output)
    assert payload["level"] == "ERROR"
    assert payload["error_type"] == "ValueError"
    assert secret not in output
    assert "interaction-token" not in output
    assert "other secret data" not in output
    configure_logging("DEBUG", secrets=(secret,))
    assert logging.getLogger("discord.http").getEffectiveLevel() >= logging.WARNING
