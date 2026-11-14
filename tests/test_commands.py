from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from argument_arena.client import ArenaClient
from argument_arena.commands import SettingsView, parse_json
from argument_arena.config import Config
from argument_arena.settings import DEFAULTS, ArenaError
from tests.helpers import A, B, active, drain, message, pending


def interaction(user=30, admin=False):
    request = SimpleNamespace(
        guild_id=123,
        channel_id=999,
        user=SimpleNamespace(id=user, bot=False, roles=[]),
        permissions=discord.Permissions(administrator=admin),
        response=SimpleNamespace(
            is_done=Mock(return_value=False), send_message=AsyncMock(), defer=AsyncMock()
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    async def deferred(**kwargs):
        request.response.is_done.return_value = True

    request.response.defer.side_effect = deferred
    return request


async def test_discord_command_tree_serializes_complete_surface_and_feature_controls(
    product, tmp_path
):
    async with ArenaClient(Config(123, tmp_path / "token"), product.arena.repo.storage) as client:
        groups = {c.name: c for c in client.tree.get_commands(guild=client.guild)}
        assert len(groups["match"].commands) <= 25
        assert {c.name for c in groups["match"].commands} >= {
            "challenge",
            "accept",
            "decline",
            "settings",
            "status",
            "submit",
            "claims",
            "check",
            "dispute",
            "pause",
            "resume",
            "extend",
            "request",
            "concede",
            "draw",
            "finish",
            "cancel",
            "result",
            "archive",
            "correct",
            "vote",
            "retry",
            "audit",
        }
        assert {c.name for c in groups["train"].commands} >= {
            "start",
            "answer",
            "hint",
            "progress",
            "fallacy",
        }
        for command in groups.values():
            serialized = command.to_dict(client.tree)
            assert serialized["name"] == command.name
        match = await pending(product.arena)
        view = SettingsView(client, match)
        assert {option.value for option in view.select.options} == set(DEFAULTS)
        assert all(": ON" in o.label or ": OFF" in o.label for o in view.select.options)
        assert not await view.interaction_check(
            SimpleNamespace(
                guild_id=456,
                response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
            )
        )
        view.stop()


async def test_setup_and_match_audit_enforce_runtime_permissions(product, tmp_path):
    async with ArenaClient(Config(123, tmp_path / "token"), product.arena.repo.storage) as client:
        client.arena = product.arena
        groups = {c.name: c for c in client.tree.get_commands(guild=client.guild)}
        denied = interaction()
        await (
            groups["settings"]
            .get_command("server")
            ._do_call(denied, {"patch": '{"max_concurrent": 9}'})
        )
        assert "Administrator" in denied.followup.send.call_args.args[0]
        match = await pending(product.arena)
        denied = interaction()
        await groups["match"].get_command("audit")._do_call(denied, {"match_id": match["id"]})
        assert "moderator" in denied.followup.send.call_args.args[0]
        allowed = interaction(40, True)
        await (
            groups["settings"]
            .get_command("server")
            ._do_call(allowed, {"patch": '{"max_concurrent": 9}'})
        )
        assert (await product.arena.config(A.guild))["max_concurrent"] == 9


async def test_private_postmatch_feedback_is_filtered_for_spectators(product, tmp_path):
    match = await active(product.arena, {"feedback": {"delivery": "private"}})
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    await drain(product)
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    await drain(product)
    async with ArenaClient(Config(123, tmp_path / "token"), product.arena.repo.storage) as client:
        client.arena = product.arena
        command = client.tree.get_command("match", guild=client.guild).get_command("result")
        spectator = interaction()
        await command._do_call(spectator, {"match_id": match["id"]})
        args = spectator.followup.send.call_args
        content = args.kwargs["file"].fp.read().decode() if "file" in args.kwargs else args.args[0]
        assert '"strengths"' not in content and '"scores"' in content
        owner = interaction(user=10)
        await command._do_call(owner, {"match_id": match["id"]})
        args = owner.followup.send.call_args
        content = args.kwargs["file"].fp.read().decode() if "file" in args.kwargs else args.args[0]
        assert '"strengths"' in content


async def test_feedback_operates_without_final_judging_and_does_not_change_outcome(product):
    match = await active(product.arena, {"judging": {"enabled": False}})
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    await drain(product)
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "inconclusive" and result["report"] is None
    assert result["feedback"][A.id]["needs"] and not result["rated"]


def test_invalid_settings_json_has_an_actionable_error():
    with pytest.raises(ArenaError, match="valid JSON"):
        parse_json("{not-json}")
    with pytest.raises(ArenaError):
        parse_json("[]")
