"""Argument Arena scenarios and launcher for SimCord's existing browser preview."""

import asyncio
import html
import subprocess
import sys
import tempfile
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import discord
from discord.ext import tasks

from argument_arena.assistance import Assistance
from argument_arena.client import ArenaClient
from argument_arena.config import Config
from argument_arena.playground_fixtures import SampleAI, SampleResearch
from argument_arena.runtime import shutdown_signals
from argument_arena.settings import Actor
from argument_arena.storage import Storage
from argument_arena.training import Training


class PlaygroundClient(ArenaClient):
    async def setup_hook(self):
        await super().setup_hook()
        self.background_work.start()

    @tasks.loop(seconds=0.5)
    async def background_work(self):
        await self.worker.once()

    async def close(self):
        self.background_work.cancel()
        await super().close()


@asynccontextmanager
async def scenario(*, configured=True):
    """Use real Discord transport simulation and throw away the database on exit."""
    import simcord

    with tempfile.TemporaryDirectory(prefix="argument-arena-playground-") as directory:
        async with Storage(Path(directory) / "arena.sqlite3") as storage:
            bot = PlaygroundClient(Config(123, Path(directory) / "unused-token"), storage)
            env = simcord.Env(bot)
            guild = env.create_guild("Argument Arena playground", id=123)
            lobby = guild.create_text_channel("lobby")
            categories = {
                route: str(guild.create_category(route.title()).id)
                for route in ("active", "completed", "cancelled")
            }
            admin_role = guild.create_role(
                "Administrator", permissions=discord.Permissions(administrator=True)
            )
            moderator_role = guild.create_role("Arena moderators")
            members = [
                guild.add_member(env.create_user("Alex")),
                guild.add_member(env.create_user("Sam")),
                guild.add_member(env.create_user("Jamie (spectator)")),
                guild.add_member(env.create_user("Kian (administrator)"), roles=[admin_role]),
                guild.add_member(env.create_user("Morgan (moderator)"), roles=[moderator_role]),
            ]
            bot.arena.clock = lambda: env.now().timestamp()
            ai = SampleAI()
            bot.assistance = Assistance(bot.arena, ai, SampleResearch(ai, bot.arena.clock))
            bot.training = Training(bot.arena, ai)
            bot.worker.assistance = bot.assistance
            bot.worker.training = bot.training
            await bot.arena.setup(
                Actor(str(members[3].id), "123", admin=True),
                {
                    "categories": categories if configured else dict.fromkeys(categories),
                    "moderator_roles": [str(moderator_role.id)],
                    "challenge_cooldown": 1,
                },
            )
            try:
                await env.start()
                await bot.get_channel(lobby.id).send(
                    "**Argument Arena playground**\n"
                    "This is a local simulation with disposable data. AI scores, feedback "
                    "and evidence are labelled samples; nothing is sent to Discord or a "
                    "model provider.\n\n"
                    "Type `/help`, or `/challenge` and choose Sam. Switch **Viewing as** "
                    "between Alex and Sam to review and confirm the challenge through "
                    "`/match`. After both confirm, return to the launcher, refresh its "
                    "channel list and open the new debate channel.\n\n"
                    "Choose Kian to explore `/admin`; Morgan has match moderation "
                    "permissions. `/train`, `/profile` and `/leaderboard` also run the "
                    "real bot code. Use SimCord's Refresh preview after background work."
                )
                await env.settle()
                yield SimpleNamespace(
                    bot=bot, env=env, guild=guild, lobby=lobby, members=members, ai=ai
                )
                env.raise_errors()
            finally:
                await env.shutdown()


def create_app(port=8765, *, configured=True):
    """Keep only scenario controls here; SimCord owns every Discord UI interaction."""
    from aiohttp import web

    @web.middleware
    async def local_only(request, handler):
        if request.host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise web.HTTPForbidden(text="Open the playground on localhost.")
        if request.headers.get("Origin") not in {None, f"http://{request.host}"}:
            raise web.HTTPForbidden(text="Use the playground's own controls.")
        try:
            response = await handler(request)
        except web.HTTPException as response:
            response.headers["Cache-Control"] = "no-store"
            raise
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; base-uri 'none'; "
                f"form-action 'self' http://127.0.0.1:{port + 1}; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
            }
        )
        return response

    app = web.Application(middlewares=[local_only], client_max_size=4096)
    lock = asyncio.Lock()
    stack, world, preview = None, None, None
    selected = None

    async def open_channel(channel):
        nonlocal preview, selected
        if preview:
            await preview.close()
        preview = await world.env.preview(
            channel, viewers=world.members, layout="channel", port=port + 1
        ).__aenter__()
        selected = channel

    async def reset(ready):
        nonlocal stack, world, preview
        if stack:
            await stack.aclose()
        stack, preview = AsyncExitStack(), None
        world = await stack.enter_async_context(scenario(configured=ready))
        await open_channel(world.lobby)

    async def lifespan(_app):
        try:
            await reset(configured)
            yield
        finally:
            if stack:
                await stack.aclose()

    def channels():
        return {
            str(channel.id): channel
            for channel in world.guild.channels.values()
            if isinstance(world.bot.get_channel(channel.id), (discord.TextChannel, discord.Thread))
        }

    async def index(request):
        buttons = "".join(
            f'<button type="submit" name="channel" value="{id}">'
            f"{html.escape(channel.name)}{' (open)' if channel.id == selected.id else ''}</button>"
            for id, channel in channels().items()
        )
        ai_state = "Unavailable service" if world.ai.unavailable else "Sample responses"
        return web.Response(
            text=f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Argument Arena playground</title><link rel="stylesheet" href="/style.css">
<script src="/launcher.js" defer></script><main>
<p class="eyebrow">ARGUMENT ARENA / LOCAL DEVELOPMENT</p>
<h1>Try the bot. Skip the deployment.</h1>
<p>Real commands and menus, running in SimCord's browser preview.</p>
<p class="sample"><strong>Sample mode:</strong> Discord is simulated. AI and search
use fixed examples. Demo data is discarded when this process restarts.</p>
<a class="primary" href="/chat" target="arena-chat">Open bot preview</a>
<section aria-labelledby="channels"><h2 id="channels">Channels</h2>
<p>Start in lobby. After both members confirm a challenge, refresh this list
and open the new match channel. Choosing a channel changes the preview tab.</p>
<form action="/channel" method="post" target="arena-chat">{buttons}</form>
<a href="/">Refresh channel list</a></section>
<section aria-labelledby="scenarios"><h2 id="scenarios">Explore a scenario</h2>
<p>Switch members with <strong>Viewing as</strong> in the preview.
Alex and Sam can debate. Kian is an administrator; Morgan is a moderator.</p>
<form method="post" action="/scenario">
<button type="submit" name="scenario" value="configured">Start over</button>
<button type="submit" name="scenario" value="unconfigured">Try missing server setup</button>
</form><p>Starting over clears only this playground's demo data.</p>
<form method="post" action="/ai"><button type="submit">AI: {ai_state} — toggle</button></form>
<p>After changing service availability, use Refresh preview
in SimCord. Retry failed work through the bot's normal menus.</p></section>
<p class="muted">Edit Python code to reload automatically, then reopen the preview.
SimCord's layout approximates Discord; a real-server check still verifies final rendering.</p>
</main></html>""",
            content_type="text/html",
        )

    async def chat(request):
        # Keep SimCord's capability out of logs and the stable launcher URL.
        raise web.HTTPFound(preview.url)

    async def channel(request):
        data = await request.post()
        target = channels().get(data.get("channel"))
        if target is None:
            raise web.HTTPBadRequest(text="Refresh the launcher and choose a current channel.")
        async with lock:
            if selected.id != target.id:
                await open_channel(target)
        raise web.HTTPFound(preview.url)

    async def change_scenario(request):
        data = await request.post()
        if data.get("scenario") not in {"configured", "unconfigured"}:
            raise web.HTTPBadRequest(text="Choose a scenario from the launcher.")
        async with lock:
            await reset(data["scenario"] == "configured")
        raise web.HTTPFound("/")

    async def toggle_ai(request):
        world.ai.unavailable = not world.ai.unavailable
        raise web.HTTPFound("/")

    async def stylesheet(request):
        return web.Response(
            text="""*{box-sizing:border-box}body{margin:0;background:#080b0d;color:#dbe3e6;
font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
main{max-width:880px;margin:0 auto;padding:56px 24px 80px;min-width:0}
h1{font-size:clamp(28px,5vw,40px);line-height:1.2;color:#f3f6f5;max-width:650px}
h2{font-size:20px;color:#f3f6f5}.eyebrow{font-size:12px;letter-spacing:.08em;color:#849094}
p{max-width:680px}.sample{padding:16px;background:#151d21;border-radius:6px}
.muted{color:#849094}section{margin:40px 0}form{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
button,a.primary{font:inherit;font-size:14px;color:#dbe3e6;padding:9px 16px;
border:1px solid #263137;border-radius:6px;background:transparent;cursor:pointer;
text-align:left;max-width:100%;overflow-wrap:anywhere}
a{color:#9cc8ff}a.primary{display:inline-block;color:#f3f6f5;background:#26343a;
text-decoration:none;font-weight:600;border-color:transparent}
button:hover,a.primary:hover{background:#314249}button:active{transform:scale(.98)}
:focus-visible{outline:2px solid #9cc8ff;outline-offset:2px}
@media(max-width:600px){main{padding:32px 16px 56px}}""",
            content_type="text/css",
        )

    async def script(request):
        return web.Response(
            text='window.addEventListener("focus", () => location.reload());',
            content_type="application/javascript",
        )

    app.cleanup_ctx.append(lifespan)
    app.add_routes(
        [
            web.get("/", index),
            web.get("/chat", chat),
            web.get("/style.css", stylesheet),
            web.get("/launcher.js", script),
            web.post("/channel", channel),
            web.post("/scenario", change_scenario),
            web.post("/ai", toggle_ai),
        ]
    )
    return app


async def serve(port, *, configured=True):
    from aiohttp import web

    runner = web.AppRunner(create_app(port, configured=configured), access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        print(f"Open http://127.0.0.1:{port} — sample data; no Discord token needed", flush=True)
        stop = asyncio.Event()
        with shutdown_signals(stop):
            await stop.wait()
    finally:
        await runner.cleanup()


def source_stamp():
    return tuple(
        (str(path), path.stat().st_mtime_ns) for path in sorted(Path(__file__).parent.glob("*.py"))
    )


def run(port=8765, *, reload=True, configured=True):
    if not 1024 <= port <= 65534:
        raise ValueError("Playground port must be from 1024 to 65534")
    if not reload:
        asyncio.run(serve(port, configured=configured))
        return
    process = None
    try:
        while True:
            stamp = source_stamp()
            argv = [
                sys.executable,
                "-m",
                "argument_arena",
                "playground",
                "--port",
                str(port),
                "--no-reload",
            ]
            if not configured:
                argv.append("--unconfigured")
            process = subprocess.Popen(argv)
            while process.poll() is None and source_stamp() == stamp:
                time.sleep(0.5)
            if process.poll() is not None:
                return
            print("Bot code changed; reloading with fresh demo data…", flush=True)
            process.terminate()
            process.wait(timeout=15)
    except KeyboardInterrupt:
        pass
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
