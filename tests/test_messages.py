import json
import re
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

from argument_arena.logging import JsonFormatter
from argument_arena.messages import failure_reason, interaction_error, job_guidance
from argument_arena.settings import ArenaError, match_settings


def test_unexpected_error_has_a_correlated_reference_without_private_payloads(caplog):
    try:
        raise RuntimeError("private answer and key https://example.org/token/secret")
    except RuntimeError as error:
        message = interaction_error(error)
    reference = re.search(r"reference `([a-f0-9]{12})`", message).group(1)
    log = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert reference in log["event"]
    assert log["error_type"] == "RuntimeError"
    assert "private answer" not in message + json.dumps(log)
    assert "secret" not in message + json.dumps(log)
    assert "already have been saved" in message
    assert "check its current status before retrying" in message


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            discord.Forbidden(
                SimpleNamespace(status=403, reason="Forbidden"),
                {"message": "private service body", "code": 50013},
            ),
            "check the bot's role",
        ),
        (
            discord.NotFound(
                SimpleNamespace(status=404, reason="Not found"), "private service body"
            ),
            "select a current item",
        ),
        (
            discord.HTTPException(
                SimpleNamespace(status=503, reason="Unavailable"), "private service body"
            ),
            "check its current status",
        ),
        (app_commands.NoPrivateMessage(), "text channel or discussion thread"),
        (app_commands.MissingPermissions(["administrator"]), "server-wide bot settings"),
        (app_commands.BotMissingPermissions(["manage_channels"]), "bot's role"),
        (
            app_commands.CommandOnCooldown(app_commands.Cooldown(1, 30), 12.2),
            "Wait 13 seconds",
        ),
    ],
)
def test_discord_failures_explain_the_recovery_without_echoing_exception_text(error, expected):
    message = interaction_error(error)
    assert expected in message
    assert "private service body" not in message


def test_background_failures_distinguish_automatic_retry_from_operator_action():
    pending = job_guidance("rate_limited", "pending")
    failed = job_guidance("rate_limited", "failed")
    training = job_guidance("credential_rejected", "failed", training=True)
    assert "scheduled another attempt" in pending and "no need to resubmit" in pending
    assert "Retry failed work" in failed and "moderator" in failed
    assert "Retry failed grading" in training and "saved answer" in training
    assert "API key" in training and "do not paste" in training
    assert "not accepted as a result" in failure_reason("ungrounded_judgment")
    assert "private unknown failure payload" not in failure_reason(
        "private unknown failure payload"
    )
    assert "per-match limits do not reset" in failure_reason("budget_or_policy_limit")
    assert "No paid fallback" in failure_reason("insufficient_balance")


def test_invalid_setting_explains_the_expected_value_without_echoing_input():
    with pytest.raises(ArenaError) as rejected:
        match_settings({"coaching": {"delivery": "a-private-key-value"}})
    message = str(rejected.value)
    assert "private, public" in message and "parameter menu" in message
    assert "a-private-key-value" not in message
    with pytest.raises(ArenaError, match="true or false"):
        match_settings({"claims": {"enabled": "false"}})
