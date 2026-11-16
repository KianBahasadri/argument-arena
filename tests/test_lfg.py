import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from argument_arena.discord_gateway import DiscordGateway, overwrites
from argument_arena.settings import Actor, ArenaError
from tests.helpers import ADMIN, SPECTATOR, A, B, drain, message
from tests.test_discord_gateway import Entity, effective, fixture_guild


async def lfg(product, channel="900"):
    match = await product.arena.open_match(A, "https://discord.com/channels/123/999")
    await product.arena.attach_channel(match["id"], channel)
    return await product.arena.repo.match(match["id"])


async def test_open_match_has_no_claim_opponent_or_response_clock(product):
    match = await lfg(product)
    assert match["state"] == "lfg" and match["players"] == [A.id]
    assert match["topic"] == "" and match["confirmed"] == []
    assert match["next"] is None and match["deadline"] is None and match["turn"] == 0
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM jobs WHERE kind='create'")) == 1
        assert not await unit.rows("SELECT id FROM jobs WHERE kind='analyze'")
    product.clock.advance(3 * 86400)
    await product.arena.tick(True)
    assert (await product.arena.repo.match(match["id"]))["state"] == "lfg"


async def test_only_opener_can_post_the_claim_and_cannot_join_themselves(product):
    match = await lfg(product)
    assert not await message(product.arena, match, B)
    assert not await product.arena.message(
        A.guild, "900", "100", A.id, "A bot claim", "url", product.clock(), bot=True
    )
    assert not await message(product.arena, match, content=" ")
    assert not await message(product.arena, match, content="x")
    assert await message(product.arena, match)
    assert not await message(product.arena, match)
    assert await message(product.arena, match, message_id="101", content="More context.")
    current = await product.arena.repo.match(match["id"])
    assert current["state"] == "lfg" and current["players"] == [A.id]
    assert current["topic"] == "The measured value is 12."
    assert current["message_count"] == 2 and current["deadline"] is None
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM jobs WHERE kind='analyze'")


async def test_first_reply_joins_atomically_and_preserves_both_opening_turns(product):
    match = await lfg(product)
    await message(product.arena, match)
    replies = await asyncio.gather(
        message(product.arena, match, B, "101", "The sample is not representative."),
        message(product.arena, match, SPECTATOR, "102", "A competing challenge."),
    )
    assert sum(replies) == 1
    current = await product.arena.repo.match(match["id"])
    challenger = B.id if replies[0] else SPECTATOR.id
    assert current["players"] == [A.id, challenger] and current["state"] == "active"
    assert current["confirmed"] == current["players"]
    assert current["turn"] == 2 and current["turn_counts"] == {A.id: 1, challenger: 1}
    assert current["next"] == A.id and current["deadline"] == product.clock() + 86400
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM messages")) == 2
        assert len(await unit.rows("SELECT id FROM jobs WHERE kind='activate'")) == 1
        assert len(await unit.rows("SELECT id FROM jobs WHERE kind='analyze'")) == 2
    await drain(product)
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM claims")) == 2
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(Actor(challenger, A.guild), match["id"], "finish")
    await drain(product)
    assert (await product.arena.result(match["id"], A.guild))["outcome"] == "judged"


async def test_lfg_claim_edits_are_used_and_deleted_claims_cannot_be_challenged(product):
    match = await lfg(product)
    await message(product.arena, match)
    await product.arena.edit_message("100", "A revised opening claim.")
    assert (await product.arena.repo.match(match["id"]))["topic"] == "A revised opening claim."
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM jobs WHERE kind='analyze'")
    await product.arena.edit_message("100", deleted=True)
    assert not await message(product.arena, match, B, "101")
    assert (await product.arena.repo.match(match["id"]))["topic"] == ""
    await message(product.arena, match, message_id="102", content="The replacement claim.")
    await message(product.arena, match, B, "103", "Here is my objection.")
    current = await product.arena.repo.match(match["id"])
    assert current["topic"] == "The replacement claim." and current["players"] == [A.id, B.id]
    async with product.arena.repo.unit() as unit:
        assert not await unit.one("SELECT id FROM jobs WHERE id='analyze:100:3'")


async def test_edited_lfg_claim_analysis_uses_latest_revision_once_matched(product):
    match = await lfg(product)
    await message(product.arena, match)
    await product.arena.edit_message("100", "The updated measurement is 13.")
    await message(product.arena, match, B, "101")
    await drain(product)
    analyses = [
        data
        for task, data, _ in product.llm.calls
        if task == "analyze" and data["message"]["id"] == "100"
    ]
    assert any(data["message"]["content"] == "The updated measurement is 13." for data in analyses)
    assert not any(data["message"]["content"] == "The measured value is 12." for data in analyses)


@pytest.mark.parametrize("turns", [{"structure": "submit"}, {"enabled": False}, {"first": 1}])
async def test_opening_pair_starts_the_next_turn_under_each_turn_policy(product, turns):
    await product.arena.setup(ADMIN, {"defaults": {"turns": turns}})
    match = await lfg(product)
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    current = await product.arena.repo.match(match["id"])
    assert current["turn"] == 2
    if turns.get("enabled") is False:
        assert current["next"] is None and current["deadline"] is None
    else:
        assert current["next"] == A.id
    if turns.get("structure") == "submit":
        with pytest.raises(ArenaError, match="new official"):
            await product.arena.submit(A, match["id"])
        await message(product.arena, match, message_id="102")
        assert (await product.arena.repo.match(match["id"]))["turn"] == 2
        await product.arena.submit(A, match["id"])
        assert (await product.arena.repo.match(match["id"]))["next"] == B.id


async def test_opener_can_cancel_without_an_opponent_and_expiry_is_unrated(product):
    match = await lfg(product)
    with pytest.raises(ArenaError, match="participants"):
        await product.arena.action(B, match["id"], "cancel")
    await product.arena.action(A, match["id"], "cancel")
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "cancelled" and not result["rated"]
    await drain(product)  # Single-player cancellations must not break profile work.
    product.clock.advance(2)
    expired = await lfg(product, "901")
    product.clock.advance(7 * 86400 + 1)
    await product.arena.tick(True)
    assert (await product.arena.result(expired["id"], A.guild))["outcome"] == "cancelled"


async def test_cooldown_capacity_and_bot_rules_cover_opening_and_joining(product):
    await product.arena.setup(ADMIN, {"max_concurrent": 1, "challenge_cooldown": 60})
    match = await lfg(product)
    with pytest.raises(ArenaError, match="cooldown"):
        await product.arena.open_match(A, "url")
    product.clock.advance(61)
    with pytest.raises(ArenaError, match="concurrent"):
        await product.arena.open_match(A, "url")
    with pytest.raises(ArenaError, match="human"):
        await product.arena.open_match(Actor("60", A.guild, bot=True), "url")
    await product.arena.open_match(B, "url")
    await message(product.arena, match)
    assert not await message(product.arena, match, B, "101")
    assert (await product.arena.repo.match(match["id"]))["state"] == "lfg"
    assert await message(product.arena, match, SPECTATOR, "102")


async def test_lfg_permissions_allow_matching_and_activation_moves_with_explicit_rules(
    product, monkeypatch
):
    match = await lfg(product)
    guild, members, bot = fixture_guild()
    config = await product.arena.config(A.guild)
    rules = overwrites(guild, match, config, members[:1], bot)
    assert effective(guild, rules, Entity(30), [guild.roles[1]]).send_messages
    gateway = DiscordGateway(SimpleNamespace(user=SimpleNamespace(id=999)), product.arena)
    post = SimpleNamespace(
        channel=SimpleNamespace(id=900),
        author=SimpleNamespace(id=30, bot=False, roles=[]),
        delete=AsyncMock(),
    )
    assert not await gateway.enforce_message(post)
    await message(product.arena, match)
    assert await gateway.enforce_message(post)
    await message(product.arena, match, B, "101")
    assert not await gateway.enforce_message(post)
    category = SimpleNamespace(id=1)
    monkeypatch.setattr(discord, "CategoryChannel", SimpleNamespace)
    guild.get_channel = lambda _: category
    gateway.client.get_guild = lambda _: guild
    channel = SimpleNamespace(edit=AsyncMock())
    gateway.channel = AsyncMock(return_value=channel)
    await gateway.permissions({"match_id": match["id"], "kind": "activate"})
    args = channel.edit.call_args.kwargs
    assert args["category"] is category and args["sync_permissions"] is False
    assert not effective(guild, args["overwrites"], Entity(30), [guild.roles[1]]).send_messages
    assert effective(guild, args["overwrites"], members[1], [guild.roles[1]]).send_messages
    await product.arena.action(A, match["id"], "concede")
    channel.edit.reset_mock()
    await gateway.permissions({"match_id": match["id"], "kind": "activate"})
    channel.edit.assert_not_awaited()


@pytest.mark.parametrize("existing_category", [False, True])
async def test_create_reuses_or_creates_exact_lfg_category_without_duplicate_channels(
    product, monkeypatch, existing_category
):
    match = await product.arena.open_match(A, "url")
    guild, _, _ = fixture_guild()

    class Category:
        def __init__(self, name):
            self.name = name

    class Channel:
        id = 900
        topic = f"Argument Arena match:{match['id']}"

    monkeypatch.setattr(discord, "CategoryChannel", Category)
    monkeypatch.setattr(discord, "TextChannel", Channel)
    category = Category("LFG")
    guild.fetch_channels = AsyncMock(
        return_value=[category] if existing_category else [Category("LFG matches")]
    )
    guild.create_category = AsyncMock(return_value=category)
    guild.create_text_channel = AsyncMock(return_value=Channel())
    gateway = DiscordGateway(SimpleNamespace(get_guild=lambda _: guild), product.arena)
    await asyncio.gather(
        gateway.create({"match_id": match["id"]}), gateway.create({"match_id": match["id"]})
    )
    guild.create_text_channel.assert_awaited_once()
    assert guild.create_text_channel.call_args.kwargs["category"] is category
    if existing_category:
        guild.create_category.assert_not_awaited()
    else:
        guild.create_category.assert_awaited_once_with("LFG", reason="Open debate matchmaking")
    current = await product.arena.repo.match(match["id"])
    assert current["state"] == "lfg" and current["channel"] == "900"


async def test_reconcile_recovers_claim_and_unknown_challenger_missed_during_restart(product):
    match = await lfg(product)

    class Channel:
        async def history(self, **kwargs):
            for id, author in [(100, 10), (101, 20), (102, 30)]:
                yield SimpleNamespace(
                    id=id,
                    author=SimpleNamespace(id=author, bot=False),
                    content=f"Argument from {author}.",
                    jump_url=f"https://discord.com/channels/123/900/{id}",
                    created_at=datetime.now(UTC),
                )

    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    gateway.channel = AsyncMock(return_value=Channel())
    await gateway.reconcile()
    await gateway.reconcile()
    current = await product.arena.repo.match(match["id"])
    assert current["state"] == "active" and current["players"] == [A.id, B.id]
    assert current["turn"] == 2 and current["message_count"] == 2
    async with product.arena.repo.unit() as unit:
        assert all(not row["deleted"] for row in await unit.rows("SELECT deleted FROM messages"))
        jobs = await unit.rows("SELECT data FROM jobs WHERE kind='analyze'")
        assert {json.loads(row["data"])["message"] for row in jobs} == {"100", "101"}


@pytest.mark.parametrize("claim", [None, "An edited claim from the outage."])
async def test_reconcile_updates_or_removes_saved_claim_before_accepting_missed_reply(
    product, claim
):
    match = await lfg(product)
    await message(product.arena, match)

    class Channel:
        async def history(self, **kwargs):
            for id, author, content in [(100, 10, claim), (101, 20, "My challenge.")]:
                if content is not None:
                    yield SimpleNamespace(
                        id=id,
                        author=SimpleNamespace(id=author, bot=False),
                        content=content,
                        jump_url=f"https://discord.com/channels/123/900/{id}",
                        created_at=datetime.now(UTC),
                    )

    gateway = DiscordGateway(SimpleNamespace(), product.arena)
    gateway.channel = AsyncMock(return_value=Channel())
    await gateway.reconcile()
    current = await product.arena.repo.match(match["id"])
    assert current["topic"] == (claim or "")
    assert current["state"] == ("active" if claim else "lfg")
    assert current["players"] == ([A.id, B.id] if claim else [A.id])
