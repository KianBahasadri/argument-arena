import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
from aiohttp.test_utils import TestClient, TestServer
from simcord import BackendError, SetupError

from argument_arena import playground
from argument_arena.playground import create_app, scenario
from argument_arena.settings import Actor


def output(result):
    return result.followups[-1] if result.followups else result.response


async def select(actor, result, value):
    message = output(result)
    menu = next(
        item
        for row in message.components
        for item in row.get("components", [])
        if any(option.get("value") == value for option in item.get("options", []))
    )
    return await actor.select(message, [value], custom_id=menu["custom_id"])


async def fill(actor, result, *values):
    fields = [item for row in result.modal["components"] for item in row["components"]]
    return await actor.submit_modal(
        result, {item["custom_id"]: value for item, value in zip(fields, values, strict=True)}
    )


async def test_real_simcord_challenge_confirmations_channel_permissions_and_result():
    async with scenario() as world:
        alex, sam, spectator, *_ = world.members
        opening = await alex.slash(world.lobby, "challenge", member=sam)
        draft = await fill(
            alex, opening, "Should the park open later?", "Keep it open", "Keep current hours"
        )
        sent = await alex.click(output(draft), label="Send challenge")
        await select(alex, sent, "accept")
        picker = await sam.slash(world.lobby, "match")
        async with world.bot.arena.repo.unit() as unit:
            match_id = (await unit.rows("SELECT id FROM matches"))[0]["id"]
        reviewed = await select(sam, picker, match_id)
        await select(sam, reviewed, "accept")
        await world.env.advance_time(1)
        match = await world.bot.arena.repo.match(match_id)
        assert match["state"] == "active" and match["channel"]
        debate = next(c for c in world.guild.channels.values() if str(c.id) == match["channel"])
        await alex.send(debate, "Longer park hours give residents more time for exercise.")
        await sam.send(debate, "Later opening could increase costs that the budget must cover.")
        with pytest.raises(BackendError, match="[Pp]ermission|50013"):
            await spectator.send(debate, "I should not be able to post an official turn.")
        panel = await alex.slash(debate, "match")
        confirm = await select(alex, panel, "concede")
        await alex.click(output(confirm), label="Confirm")
        await world.env.advance_time(1)
        result = await world.bot.arena.result(match_id, "123")
        assert result["outcome"] == "concession" and result["winner"] == str(sam.id)
        completed = (await world.bot.arena.config("123"))["categories"]["completed"]
        assert str(world.bot.get_channel(debate.id).category_id) == completed
        world.env.raise_errors()


async def test_real_simcord_training_feedback_and_ephemeral_permissions():
    async with scenario() as world:
        alex, sam, *_ = world.members
        training = await alex.slash(world.lobby, "train")
        start = await select(alex, training, "start")
        mode = await select(alex, start, "mixed")
        topic = await select(alex, mode, "1")
        exercise = await fill(alex, topic, "Public transport")
        answer = await select(alex, exercise, "answer")
        await fill(alex, answer, "The stated premise does not establish that conclusion.")
        await world.env.advance_time(1)
        current = await select(alex, await alex.slash(world.lobby, "train"), "current")
        assert "Sample feedback" in str(output(current).embeds[0].to_dict())
        assert output(current).ephemeral
        with pytest.raises((BackendError, SetupError)):
            await sam.select(output(current), ["progress"])
        world.env.raise_errors()


def available_ports():
    for _ in range(20):
        with socket.socket() as first, socket.socket() as second:
            first.bind(("127.0.0.1", 0))
            port = first.getsockname()[1]
            try:
                second.bind(("127.0.0.1", port + 1))
            except OSError:
                continue
            return port
    raise AssertionError("Could not reserve two local preview ports")


async def test_launcher_opens_native_preview_without_exposing_its_capability_in_html():
    port = available_ports()
    async with TestClient(TestServer(create_app(port), port=port)) as browser:
        home = await browser.get("/")
        assert home.status == 200
        page = await home.text()
        assert "Open bot preview" in page and "lobby" in page
        assert "Content-Security-Policy" in home.headers
        preview = await browser.get("/chat", allow_redirects=False)
        location = preview.headers["Location"]
        assert preview.status == 302 and location.startswith(f"http://127.0.0.1:{port + 1}/#")
        assert location not in page
        native = await browser.session.get(location.split("#")[0])
        assert native.status == 200 and "SimCord" in await native.text()
        rejected = await browser.post("/ai", headers={"Origin": "https://unrelated.example"})
        assert rejected.status == 403
        bridge_rejected = await browser.session.post(
            location.split("#")[0] + "api/pages",
            headers={"Origin": "https://unrelated.example"},
        )
        assert bridge_rejected.status == 403
        reset = await browser.post("/scenario", data={"scenario": "unconfigured"})
        assert reset.status == 200
        reopened = await browser.get("/chat", allow_redirects=False)
        assert reopened.status == 302 and reopened.headers["Location"] != location
        assert (await browser.post("/ai")).status == 200


async def test_browser_session_runs_match_creation_and_grading_without_manual_time(monkeypatch):
    worlds = []

    @asynccontextmanager
    async def capture_world(**kwargs):
        async with scenario(**kwargs) as world:
            worlds.append(world)
            yield world

    monkeypatch.setattr(playground, "scenario", capture_world)
    port = available_ports()
    async with TestClient(TestServer(create_app(port), port=port)):
        world = worlds[0]
        alex, sam = [Actor(str(member.id), "123") for member in world.members[:2]]
        started = world.env.now()
        match = await world.bot.arena.challenge(
            alex,
            sam.id,
            "Should the park open later?",
            ["Open later", "Keep current hours"],
            f"https://discord.com/channels/123/{world.lobby.id}",
        )
        await world.bot.arena.accept(alex, match["id"], match["revision"])
        await world.bot.arena.accept(sam, match["id"], match["revision"])
        await world.bot.training.start(alex)
        await world.bot.training.answer(alex, "The premise does not establish the conclusion.")

        # Poll durable results, without requests or advance_time driving the worker.
        async with asyncio.timeout(5):
            while True:
                current = await world.bot.arena.repo.match(match["id"])
                progress = await world.bot.training.progress(alex)
                if current["channel"] and progress["attempts"]:
                    break
                await asyncio.sleep(0.05)

        assert current["state"] == "active"
        assert world.bot.get_channel(int(current["channel"])) is not None
        assert progress["attempts"] == 1
        assert "Sample feedback" in str(progress["latest"])
        assert world.env.now() > started
        world.env.raise_errors()
