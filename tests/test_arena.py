import asyncio
import json

import pytest

from argument_arena.arena import Arena
from argument_arena.settings import Actor, ArenaError
from argument_arena.storage import Storage
from tests.helpers import ADMIN, SPECTATOR, STAFF, A, B, active, message, pending


async def test_setup_limits_and_audit(product):
    arena = product.arena
    with pytest.raises(ArenaError, match="Administrator"):
        await arena.setup(STAFF, {})
    await arena.setup(
        ADMIN, {"max_concurrent": 1, "presets": {"custom": {"research": {"enabled": False}}}}
    )
    match = await pending(arena, preset="custom")
    assert not match["settings"]["research"]["enabled"]
    product.clock.advance(2)
    with pytest.raises(ArenaError, match="concurrent"):
        await pending(arena)
    async with arena.repo.unit() as unit:
        events = await unit.rows("SELECT * FROM events WHERE match_id=?", ("guild:123",))
    assert len(events) >= 2


async def test_mutual_identical_revision_and_permissions(product):
    arena = product.arena
    match = await pending(arena)
    await arena.accept(A, match["id"], 1)
    changed = await arena.settings(
        B, match["id"], {"coaching": {"enabled": True}}, ["Assigned A", "Assigned B"]
    )
    assert changed["confirmed"] == []
    with pytest.raises(ArenaError, match="Settings changed"):
        await arena.accept(A, match["id"], 1)
    with pytest.raises(ArenaError, match="participants"):
        await arena.accept(SPECTATOR, match["id"], 2)
    with pytest.raises(ArenaError, match="another server"):
        await arena.settings(Actor(A.id, "999"), match["id"])
    result = await asyncio.gather(arena.accept(A, match["id"], 2), arena.accept(B, match["id"], 2))
    assert result[-1]["state"] == "starting"
    assert result[-1]["positions"] == ["Assigned A", "Assigned B"]
    await arena.attach_channel(match["id"], "1234")
    with pytest.raises(ArenaError, match="locked"):
        await arena.settings(A, match["id"], {"judging": {"enabled": False}})
    async with arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM jobs WHERE kind='create'")) == 1


async def test_only_required_official_response_advances_clock(product):
    arena = product.arena
    match = await active(arena)
    deadline = match["deadline"]
    assert deadline == product.clock() + 86400
    product.clock.advance(100)
    assert not await message(arena, match, B)
    assert not await message(arena, match, SPECTATOR)
    assert not await arena.message(
        A.guild, "thread-id", "101", A.id, "thread chatter", "url", product.clock()
    )
    assert not await arena.message(
        A.guild, match["channel"], "102", A.id, "bot", "url", product.clock(), bot=True
    )
    assert (await arena.repo.match(match["id"]))["deadline"] == deadline
    assert await message(arena, match)
    assert not await message(arena, match)  # Duplicate Gateway delivery.
    current = await arena.repo.match(match["id"])
    assert current["next"] == B.id and current["deadline"] == product.clock() + 86400
    await arena.edit_message("100", "A revised claim.")
    assert (await arena.repo.match(match["id"]))["deadline"] == current["deadline"]
    await arena.edit_message("100", deleted=True)
    async with arena.repo.unit() as unit:
        versions = await unit.rows("SELECT * FROM message_versions WHERE message_id='100'")
    assert [v["revision"] for v in versions] == [1, 2, 3]


async def test_submit_mode_needs_new_message_and_is_idempotent(product):
    arena = product.arena
    match = await active(arena, {"turns": {"structure": "submit"}})
    with pytest.raises(ArenaError, match="Post a new"):
        await arena.submit(A, match["id"])
    await message(arena, match)
    assert (await arena.repo.match(match["id"]))["next"] == A.id
    await arena.submit(A, match["id"])
    with pytest.raises(ArenaError, match="required"):
        await arena.submit(A, match["id"])
    await message(arena, match, B, "101")
    await arena.submit(B, match["id"])
    with pytest.raises(ArenaError, match="new official"):
        await arena.submit(A, match["id"])


async def test_flexible_order_has_no_implicit_forfeit_clock(product):
    arena = product.arena
    match = await active(arena, {"turns": {"enabled": False}})
    assert match["next"] is None and match["deadline"] is None
    await arena.action(A, match["id"], "request", {"speaker": B.id})
    requested = await arena.action(B, match["id"], "request", {"speaker": B.id})
    assert requested["next"] == B.id
    deadline = requested["deadline"]
    await message(arena, match, A)
    assert (await arena.repo.match(match["id"]))["deadline"] == deadline
    await message(arena, match, B, "101")
    assert (await arena.repo.match(match["id"]))["next"] is None


async def test_pause_resume_extend_require_peer_or_staff(product):
    arena = product.arena
    match = await active(arena)
    proposed = await arena.action(A, match["id"], "pause")
    assert proposed["state"] == "active"
    paused = await arena.action(B, match["id"], "pause")
    assert paused["state"] == "paused" and paused["remaining"] == 86400
    product.clock.advance(10000)
    await arena.action(A, match["id"], "extend", {"hours": 2})
    paused = await arena.action(B, match["id"], "extend", {"hours": 2})
    assert paused["remaining"] == 93600
    resumed = await arena.action(STAFF, match["id"], "resume")
    assert resumed["deadline"] == product.clock() + 93600
    with pytest.raises(ArenaError):
        await arena.action(SPECTATOR, match["id"], "cancel")


async def test_reminders_forfeit_race_and_once_only_results(product):
    arena = product.arena
    match = await active(arena)
    product.clock.now = match["deadline"] - 3600
    async with arena.repo.unit() as unit:
        await unit.save("worker", "clock", {"at": product.clock() - 15, "connected": True})
    await arena.tick(True)
    await arena.tick(True)
    async with arena.repo.unit() as unit:
        reminders = await unit.rows("SELECT id FROM jobs WHERE id LIKE 'reminder:%'")
    assert len(reminders) == 1
    product.clock.now = match["deadline"] + 1
    async with arena.repo.unit() as unit:
        await unit.save("worker", "clock", {"at": product.clock() - 15, "connected": True})
    await asyncio.gather(arena.tick(True), arena.tick(True))
    result = await arena.result(match["id"], A.guild)
    assert result["outcome"] == "forfeit" and result["winner"] == B.id
    async with arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT * FROM results")) == 1
        assert len(await unit.rows("SELECT * FROM events WHERE kind='closed'")) == 1
    assert not await message(arena, match)


async def test_restart_and_disconnected_intervals_extend_before_forfeit(product, tmp_path):
    arena = product.arena
    match = await active(arena)
    await arena.tick(True)
    product.clock.advance(2 * 86400)
    restarted = Arena(arena.repo.storage, product.clock)
    await restarted.tick(True)
    extended = await restarted.repo.match(match["id"])
    assert extended["state"] == "active" and extended["deadline"] > product.clock()
    product.clock.advance(20)
    await restarted.tick(False)
    product.clock.advance(20)
    await restarted.tick(True)
    assert (await restarted.repo.match(match["id"]))["deadline"] == extended["deadline"] + 40
    # Open a real second storage instance only after the original is no longer in a transaction.
    async with Storage(tmp_path / "arena.sqlite3") as storage:
        restored = Arena(storage, product.clock)
        assert (await restored.repo.match(match["id"]))["settings"] == match["settings"]


@pytest.mark.parametrize(
    "action,outcome", [("draw", "draw"), ("cancel", "cancelled"), ("finish", "inconclusive")]
)
async def test_agreed_endings_and_archival_policy(product, action, outcome):
    arena = product.arena
    match = await active(arena, {"judging": {"enabled": False}, "archive": {"enabled": False}})
    await arena.action(A, match["id"], action)
    assert (await arena.repo.match(match["id"]))["state"] == "active"
    await arena.action(B, match["id"], action)
    assert (await arena.result(match["id"], A.guild))["outcome"] == outcome
    async with arena.repo.unit() as unit:
        job = await unit.one("SELECT data FROM jobs WHERE kind='archive'")
    assert not json.loads(job["data"])["move"]


async def test_limits_and_audience_stay_separate(product):
    arena = product.arena
    match = await active(
        arena,
        {
            "judging": {"enabled": False},
            "limits": {"enabled": True, "rounds": 1, "characters": 30},
            "audience": {"enabled": True},
        },
    )
    assert not await message(arena, match, content="x" * 31)
    await message(arena, match)
    await message(arena, match, B, "101")
    assert (await arena.repo.match(match["id"]))["state"] == "closed"
    await arena.vote(SPECTATOR, match["id"], A.id)
    with pytest.raises(ArenaError, match="spectators"):
        await arena.vote(A, match["id"], A.id)
    result = await arena.result(match["id"], A.guild)
    assert result["audience_votes"][A.id] == 1 and result["winner"] is None


async def test_server_defaults_prefix_and_public_history(product):
    await product.arena.setup(
        ADMIN, {"defaults": {"inactivity": {"hours": 48}}, "match_prefix": "arena-"}
    )
    match = await product.arena.challenge(
        A, B.id, "A configured topic", ["Support", "Oppose"], "https://discord.com/channels/123/999"
    )
    assert match["id"].startswith("arena-") and match["settings"]["inactivity"]["hours"] == 48
    await product.arena.action(B, match["id"], "decline")
    history = await product.arena.history(A.guild, A.id)
    assert history["statistics"]["cancelled"] == 1
    assert history["matches"][0]["link"].endswith("/999")
    assert "feedback" not in history["matches"][0]


async def test_missing_channel_pauses_instead_of_forfeiting_and_staff_can_resolve(product):
    match = await active(product.arena)
    await product.arena.channel_missing(match["channel"])
    product.clock.advance(172800)
    await product.arena.tick(True)
    paused = await product.arena.repo.match(match["id"])
    assert paused["state"] == "paused" and paused["deadline"] is None
    assert paused["channel_unavailable"]
    with pytest.raises(ArenaError, match="moderator"):
        await product.arena.close_match(
            SPECTATOR, match["id"], "cancelled", None, "Channel permanently unavailable."
        )
    result = await product.arena.close_match(
        STAFF, match["id"], "cancelled", None, "Channel permanently unavailable."
    )
    assert result["staff_review"]["actor"] == STAFF.id and result["outcome"] == "cancelled"
