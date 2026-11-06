from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from argument_arena.discord_gateway import DiscordGateway, overwrites
from tests.helpers import ADMIN, SPECTATOR, A, B, active, message, pending


@dataclass(frozen=True)
class Entity:
    id: int
    permissions: object = None


def fixture_guild():
    everyone, ordinary, staff = Entity(123), Entity(6), Entity(7)
    a, b, bot = Entity(10), Entity(20), Entity(999)
    guild = SimpleNamespace(
        id=123,
        me=bot,
        roles=[everyone, ordinary, staff],
        get_member=lambda id: {10: a, 20: b}.get(id),
        get_channel=Mock(return_value=SimpleNamespace(id=4)),
        fetch_member=AsyncMock(),
    )
    return guild, (a, b), bot


def effective(guild, rules, member, roles):
    permissions = discord.Permissions(
        view_channel=True,
        send_messages=True,
        send_messages_in_threads=True,
        create_public_threads=True,
        add_reactions=True,
        use_application_commands=True,
    )
    allow, deny = rules[guild.roles[0]].pair()
    permissions.handle_overwrite(allow.value, deny.value)
    allows, denies = 0, 0
    for role in roles:
        allow, deny = rules[role].pair()
        allows |= allow.value
        denies |= deny.value
    permissions.handle_overwrite(allows, denies)
    if member in rules:
        allow, deny = rules[member].pair()
        permissions.handle_overwrite(allow.value, deny.value)
    return permissions


async def test_effective_spectator_role_denies_threads_reactions_commands_and_staff(product):
    match = await active(product.arena)
    config = await product.arena.config(A.guild)
    guild, members, bot = fixture_guild()
    rules = overwrites(guild, match, config, members, bot)
    spectator = effective(guild, rules, Entity(30), [guild.roles[1]])
    assert spectator.view_channel and not spectator.send_messages
    assert spectator.send_messages_in_threads and spectator.create_public_threads
    assert spectator.add_reactions and spectator.use_application_commands
    assert rules[guild.roles[1]].manage_webhooks is False
    assert rules[guild.roles[1]].manage_channels is False
    assert rules[guild.roles[2]].manage_threads is True
    assert effective(guild, rules, members[0], [guild.roles[1]]).send_messages
    assert effective(guild, rules, Entity(50), [guild.roles[2]]).send_messages
    assert effective(guild, rules, bot, []).send_messages
    closed = overwrites(guild, match, config, members, bot, closed=True)
    assert not effective(guild, closed, members[0], [guild.roles[1]]).send_messages
    assert effective(guild, closed, Entity(30), []).send_messages_in_threads
    match["settings"]["archive"]["lock_threads"] = True
    closed = overwrites(guild, match, config, members, bot, closed=True)
    assert not effective(guild, closed, Entity(30), []).send_messages_in_threads


async def test_disabled_spectator_features_and_paused_posting(product):
    match = await active(
        product.arena, {"reactions": {"enabled": False}, "threads": {"enabled": False}}
    )
    guild, members, bot = fixture_guild()
    match["state"] = "paused"
    rules = overwrites(guild, match, await product.arena.config(A.guild), members, bot)
    spectator = effective(guild, rules, Entity(30), [guild.roles[1]])
    assert not spectator.add_reactions and not spectator.create_public_threads
    assert (
        not spectator.send_messages_in_threads
        and not effective(guild, rules, members[0], []).send_messages
    )


async def test_create_recovers_channel_created_before_database_ack(product, monkeypatch):
    match = await pending(product.arena)
    await product.arena.accept(A, match["id"], 1)
    await product.arena.accept(B, match["id"], 1)
    guild, _, _ = fixture_guild()

    class Channel:
        id = 9999
        topic = f"Argument Arena match:{match['id']}"

    monkeypatch.setattr(discord, "TextChannel", Channel)
    guild.fetch_channels = AsyncMock(return_value=[Channel()])
    guild.create_text_channel = AsyncMock()
    gateway = DiscordGateway(SimpleNamespace(get_guild=lambda _: guild), product.arena)
    await gateway.create({"match_id": match["id"]})
    await gateway.create({"match_id": match["id"]})
    assert (await product.arena.repo.match(match["id"]))["channel"] == "9999"
    guild.create_text_channel.assert_not_awaited()


async def test_archival_routes_and_never_syncs_category_permissions(product, monkeypatch):
    match = await active(product.arena, {"archive": {"lock_threads": True}})
    await product.arena.action(A, match["id"], "concede")
    guild, _, _ = fixture_guild()

    class Category:
        def __init__(self, id):
            self.id = id

    monkeypatch.setattr(discord, "CategoryChannel", Category)
    guild.get_channel = lambda id: Category(id)
    thread = SimpleNamespace(edit=AsyncMock())
    channel = SimpleNamespace(edit=AsyncMock(), threads=[thread])
    gateway = DiscordGateway(SimpleNamespace(get_guild=lambda _: guild), product.arena)
    gateway.channel = AsyncMock(return_value=channel)
    await gateway.archive({"match_id": match["id"], "data": {"move": True}})
    args = channel.edit.call_args.kwargs
    assert args["category"].id == 2 and args["sync_permissions"] is False
    assert args["overwrites"][Entity(10)].send_messages is False
    thread.edit.assert_awaited_once_with(
        locked=True, archived=True, reason="Accepted closure policy"
    )
    assert (await product.arena.repo.match(match["id"]))["archived"]
    channel.edit.reset_mock()
    await gateway.archive({"match_id": match["id"], "data": {"move": False}})
    assert "category" not in channel.edit.call_args.kwargs
    assert (await product.arena.repo.match(match["id"]))["archived"]


async def test_notice_resolves_ambiguous_send_and_suppresses_mentions(product):
    match = await active(product.arena)
    sent = []

    class Channel:
        async def history(self, **kwargs):
            for item in sent:
                yield item

        async def send(self, content, **kwargs):
            assert kwargs["allowed_mentions"].everyone is False
            item = SimpleNamespace(
                id=len(sent) + 1, content=content, author=SimpleNamespace(id=999)
            )
            sent.append(item)
            return item

    client = SimpleNamespace(user=SimpleNamespace(id=999))
    gateway = DiscordGateway(client, product.arena)
    gateway.channel = AsyncMock(return_value=Channel())
    job = {
        "id": "delivery-test",
        "match_id": match["id"],
        "data": {"text": "@everyone " + "x" * 4000},
    }
    await gateway.notice(job)
    assert len(sent) == 3
    async with product.arena.repo.unit() as unit:
        await unit.db.execute("DELETE FROM documents WHERE kind='delivery'")
    await gateway.notice(job)
    assert len(sent) == 3


async def test_reconciliation_recovers_turns_and_detects_missed_edits_and_deletes(product):
    match = await active(product.arena)
    await message(product.arena, match)
    remote = [
        SimpleNamespace(
            id=100,
            content="A revised value is 13.",
            author=SimpleNamespace(id=10, bot=False),
            jump_url="https://discord.com/channels/123/900/100",
            created_at=datetime.now(UTC),
        ),
        SimpleNamespace(
            id=101,
            content="The contrary record needs investigation.",
            author=SimpleNamespace(id=20, bot=False),
            jump_url="https://discord.com/channels/123/900/101",
            created_at=datetime.now(UTC),
        ),
    ]

    class Channel:
        async def history(self, **kwargs):
            for item in remote:
                yield item

    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    gateway.channel = AsyncMock(return_value=Channel())
    await gateway.reconcile()
    current = await product.arena.repo.match(match["id"])
    assert current["turn"] == 2 and current["next"] == A.id
    async with product.arena.repo.unit() as unit:
        row = await unit.one("SELECT revision,content FROM messages WHERE id='100'")
    assert row["revision"] == 2 and row["content"] == remote[0].content
    remote.clear()
    await gateway.reconcile()
    async with product.arena.repo.unit() as unit:
        assert all(r["deleted"] for r in await unit.rows("SELECT deleted FROM messages"))


async def test_manual_archival_requires_staff_and_finished_state(product):
    match = await active(product.arena)
    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    with pytest.raises(ValueError, match="moderator"):
        await gateway.manual_archive(SPECTATOR, match["id"])
    with pytest.raises(ValueError, match="completed"):
        await gateway.manual_archive(ADMIN, match["id"])
    await product.arena.action(A, match["id"], "concede")
    assert "queued" in await gateway.manual_archive(ADMIN, match["id"])


async def test_spectator_posting_is_removed_while_permissions_are_reconciled(product):
    match = await active(product.arena)
    gateway = DiscordGateway(SimpleNamespace(user=SimpleNamespace(id=999)), product.arena)
    post = SimpleNamespace(
        channel=SimpleNamespace(id=int(match["channel"])),
        author=SimpleNamespace(id=30, roles=[], guild_permissions=discord.Permissions.none()),
        delete=AsyncMock(),
    )
    assert not await gateway.enforce_message(post)
    post.delete.assert_awaited_once()
    post.author.id = 10
    assert await gateway.enforce_message(post)


async def test_closed_channel_reconciliation_detects_missed_edits(product):
    match = await active(product.arena)
    await message(product.arena, match)
    await product.arena.action(A, match["id"], "concede")

    class Channel:
        async def history(self, **kwargs):
            yield SimpleNamespace(
                id=100,
                content="Changed after completion.",
                author=SimpleNamespace(id=10, bot=False),
                jump_url="https://discord.com/channels/123/900/100",
                created_at=datetime.now(UTC),
            )

    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    gateway.channel = AsyncMock(return_value=Channel())
    await gateway.reconcile()
    assert (await product.arena.result(match["id"], A.guild))["review_needed"]


async def test_delayed_correction_is_suppressed_after_source_edit(product):
    from tests.helpers import drain

    match = await active(product.arena)
    product.llm.responses["research"] = {
        "verdict": "contradicted",
        "confidence": 0.95,
        "source_ids": ["S1"],
        "explanation": "The primary record contradicts the quoted measurement.",
    }
    await message(product.arena, match)
    await drain(product)
    async with product.arena.repo.unit() as unit:
        job = await unit.one("SELECT * FROM jobs WHERE id LIKE 'correction:%'")
    import json

    job["data"] = json.loads(job["data"])
    await product.arena.edit_message("100", "A corrected value is 13.")
    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    gateway.channel = AsyncMock()
    await gateway.notice(job)
    gateway.channel.assert_not_awaited()
