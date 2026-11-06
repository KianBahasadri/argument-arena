from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord import app_commands

from argument_arena.client import ArenaClient
from argument_arena.config import Config


def interaction(guild_id=123, admin=True, done=False):
    return SimpleNamespace(
        guild_id=guild_id,
        permissions=discord.Permissions(administrator=admin),
        response=SimpleNamespace(send_message=AsyncMock(), is_done=Mock(return_value=done)),
        followup=SimpleNamespace(send=AsyncMock()),
    )


async def test_setup_sync_and_reconnect_lifecycle(tmp_path):
    config = Config(123, tmp_path / "token", tmp_path)
    async with ArenaClient(config, SimpleNamespace(check=AsyncMock())) as client:
        client.tree.sync = AsyncMock()
        client.get_guild = Mock(return_value=object())
        await client.setup_hook()
        client.tree.sync.assert_awaited_once_with(guild=client.guild)
        await client.on_connect()
        await client.on_ready()
        assert client.gateway_ready
        await client.on_disconnect()
        assert not client.gateway_ready
        await client.on_resumed()
        assert client.gateway_ready
        await client.on_ready()
        client.tree.sync.assert_awaited_once()
        assert client.intents.guild_messages and client.intents.message_content
        assert client.intents.guild_reactions and not client.intents.members
        commands = client.tree.get_commands(guild=client.guild)
        assert {command.name for command in commands} == {
            "diagnostic",
            "match",
            "profile",
            "train",
            "settings",
            "setup",
            "leaderboard",
        }
        assert commands[0].guild_only
        assert commands[0].default_permissions.administrator
    assert client.is_closed()
    assert not client.gateway_ready


async def test_sync_can_be_disabled_and_missing_guild_not_ready(tmp_path):
    config = Config(123, tmp_path / "token", tmp_path, sync_commands=False)
    async with ArenaClient(config, SimpleNamespace(check=AsyncMock())) as client:
        client.tree.sync = AsyncMock()
        await client.setup_hook()
        client.tree.sync.assert_not_awaited()
        await client.on_ready()
        assert not client.gateway_ready
        assert not await client.tree.interaction_check(interaction(guild_id=None))
        assert not await client.tree.interaction_check(interaction(guild_id=124))
        assert await client.tree.interaction_check(interaction())


async def test_diagnostic_checks_storage_and_permissions(tmp_path):
    storage = SimpleNamespace(check=AsyncMock())
    async with ArenaClient(Config(123, tmp_path / "token"), storage) as client:
        denied = interaction(admin=False)
        await client.diagnostic(denied)
        storage.check.assert_not_awaited()
        allowed = interaction()
        command = client.tree.get_command("diagnostic", guild=client.guild)
        await command._do_call(allowed, {})
        storage.check.assert_awaited_once()
        assert allowed.response.send_message.call_args.kwargs["ephemeral"] is True
        assert "storage OK" in allowed.response.send_message.call_args.args[0]


async def test_command_error_responds_even_after_defer(tmp_path):
    async with ArenaClient(Config(123, tmp_path / "token"), Mock()) as client:
        for done in (False, True):
            request = interaction(done=done)
            await client.tree.on_error(request, app_commands.AppCommandError("private details"))
            response = request.followup.send if done else request.response.send_message
            response.assert_awaited_once()
            assert "private details" not in response.call_args.args[0]
        try:
            raise ValueError("private Gateway payload")
        except ValueError:
            await client.on_error("on_message", "private message")
