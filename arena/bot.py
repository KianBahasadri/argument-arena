"""Discord transport: commands, channel permissions and restartable work delivery."""
from __future__ import annotations

import asyncio
import io
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from collections import defaultdict
from typing import Any
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands

from .config import Config
from .core import Arena, DomainError
from .intelligence import Intelligence
from .profiles import Profiles
from .store import Store
from .training import Training

log = logging.getLogger(__name__)


def parse_patch(value: str) -> dict:
    """Only accept bounded JSON objects, never expressions or executable code."""
    if len(value) > 8000:
        raise DomainError("Settings JSON is too long (maximum 8000 characters).")
    try:
        patch = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DomainError(f"Invalid JSON: {exc.msg}.") from exc
    if not isinstance(patch, dict):
        raise DomainError("Settings must be a JSON object, for example {\"coaching\": true}.")
    return patch


def permission_overwrites(guild, match: dict, moderator_role_ids=(), closed=False, members=None) -> dict:
    """Keep audience discussion in threads and official speech in the main channel."""
    settings = match["settings"]
    threads = bool(settings.get("discussion_threads", settings.get("public_threads", True)))
    reactions = bool(settings.get("spectator_reactions", True))
    archive_threads = bool(settings.get("archive_threads", False))
    threads = threads and not (closed and archive_threads)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False,
            add_reactions=reactions, create_public_threads=threads,
            create_private_threads=False, send_messages_in_threads=threads,
            use_application_commands=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_channels=True, manage_messages=True, manage_threads=True,
            create_public_threads=True, send_messages_in_threads=True,
        ),
    }
    members = members or {}
    for user_id in match["participants"]:
        member = members.get(user_id) or guild.get_member(user_id)
        if member is not None:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True, send_messages=(not closed and match["status"] == "active" and
                    (not settings.get("turn_enforcement", True) or match.get("next_speaker_id") == user_id)),
                read_message_history=True, add_reactions=reactions,
                create_public_threads=threads, send_messages_in_threads=threads,
                use_application_commands=True,
            )
    for role_id in moderator_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_messages=True, manage_threads=True,
                send_messages_in_threads=True, use_application_commands=True,
            )
    return overwrites


def match_summary(match: dict) -> str:
    participants = " vs ".join(f"<@{uid}>" for uid in match["participants"])
    text = f"**Match {match['id']} — {match['status']}**\n{participants}\n{match['topic']}"
    for user_id, position in match.get("positions", {}).items():
        text += f"\n<@{user_id}>: {position}"
    if match.get("origin_url"):
        text += f"\nOrigin: {match['origin_url']}"
    if match.get("next_speaker_id"):
        text += f"\nNext speaker: <@{match['next_speaker_id']}>"
    if match.get("deadline"):
        text += f" — response due <t:{int(match['deadline'])}:F>"
    if match.get("channel_id"):
        text += f"\nChannel: <#{match['channel_id']}>"
    if (match.get("result") or {}).get("evidence_stale"):
        text += "\nEvidence changed after judgment; staff review is required. The stored result is historical."
    if match.get("result"):
        text += "\nResult: " + str(match["result"].get("outcome", "recorded"))
    return text[:1900]


async def respond(interaction, content: str = "", *, data=None, ephemeral=True, view=None):
    """Attach long structured reports rather than silently dropping their evidence."""
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}
    if view is not None:
        kwargs["view"] = view
    if data is not None:
        body = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        if len(content) + len(body) <= 1850:
            content += f"\n```json\n{body}\n```"
        else:
            kwargs["file"] = discord.File(io.BytesIO(body.encode()), filename="arena-report.json")
            content += "\nFull settings or report attached."
    kwargs["content"] = (content or "Done.")[:1950]
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)
    return await interaction.response.send_message(**kwargs)


class JobDeferred(Exception):
    """Work is waiting on another durable job, without consuming a retry."""
    def __init__(self, message, delay=5):
        super().__init__(message)
        self.delay = delay


class SettingsModal(discord.ui.Modal, title="Propose match settings"):
    patch = discord.ui.TextInput(
        label="Settings JSON (both participants must accept)",
        style=discord.TextStyle.paragraph, max_length=4000,
        placeholder='{"coaching": true, "response_hours": 48}',
    )

    def __init__(self, bot: ArenaBot, match_id: str):
        super().__init__()
        self.bot = bot
        self.match_id = match_id

    async def on_submit(self, interaction):
        try:
            self.bot.checked_match(interaction, self.match_id, participant=True)
            await interaction.response.defer(ephemeral=True)
            match = self.bot.arena.propose_settings(
                self.match_id, interaction.user.id, parse_patch(self.patch.value)
            )
            await respond(interaction, "Settings proposed. Both participants must run /match accept.",
                          data=match.get("settings_proposal") or match["settings"])
            await self.bot.announce(match, "New settings proposed; review /match settings and use /match accept.")
        except DomainError as exc:
            await respond(interaction, str(exc))


class MatchView(discord.ui.View):
    """Persistent buttons delegate authorization to the same handlers as slash commands."""
    def __init__(self, bot: ArenaBot, match_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id
        for action, label, style in (
            ("accept", "Accept current settings", discord.ButtonStyle.success),
            ("decline", "Decline", discord.ButtonStyle.danger),
            ("settings", "Review / change settings", discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, style=style, custom_id=f"arena:{match_id}:{action}")
            button.callback = self.callback_for(action)
            self.add_item(button)
        from .core import DEFAULT_SETTINGS
        current = bot.arena.get_match(match_id)["settings"]
        select = discord.ui.Select(
            placeholder="Choose a feature to switch on or off", custom_id=f"arena:{match_id}:toggle", row=1,
            options=[discord.SelectOption(label=f"{key}: {'on' if current[key] else 'off'}"[:100], value=key)
                     for key, value in DEFAULT_SETTINGS.items() if isinstance(value, bool)],
        )
        async def toggle(interaction):
            try:
                match = self.bot.checked_match(interaction, self.match_id, participant=True)
                await interaction.response.defer(ephemeral=True)
                key = select.values[0]
                proposed = match.get("settings_proposal", {}).get("settings", match["settings"])
                match = self.bot.arena.propose_settings(self.match_id, interaction.user.id, {key: not proposed[key]})
                await respond(interaction, "Feature change proposed. Both participants must accept the new settings.",
                              data=match.get("settings_proposal") or match["settings"])
            except DomainError as exc:
                await respond(interaction, str(exc))
        select.callback = toggle
        self.add_item(select)

    def callback_for(self, action):
        async def callback(interaction):
            try:
                self.bot.checked_match(interaction, self.match_id, participant=True)
                if action == "settings":
                    await interaction.response.send_modal(SettingsModal(self.bot, self.match_id))
                else:
                    await interaction.response.defer(ephemeral=True)
                    match = await self.bot.accept_or_decline(interaction, self.match_id, action)
                    await respond(interaction, match_summary(match))
            except DomainError as exc:
                await respond(interaction, str(exc))
        return callback

    async def on_error(self, interaction, error, item):
        log.exception("Match button failed", exc_info=error)
        await respond(interaction, "Discord could not complete this action. The persisted match can be retried with /match status.")


class ArenaBot(commands.Bot):
    def __init__(self, config: Config, store: Store | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.store = store or Store(config.database_path)
        self.arena = Arena(self.store)
        self.intelligence = Intelligence(self.store, config.as_dict())
        self.training = Training(self.store, self.intelligence)
        self.profiles = Profiles(self.store, self.intelligence)
        self.match_locks = defaultdict(asyncio.Lock)
        self.background: list[asyncio.Task] = []
        self.tree.on_error = self.command_error
        self._recovered = False

    async def setup_hook(self):
        await self.add_cog(ArenaCommands(self))
        for match in self.store.list("matches"):
            if match["status"] in ("pending", "ready", "active", "paused"):
                self.add_view(MatchView(self, match["id"]))
        for job in self.store.list("jobs", status="running"):
            job["status"] = "pending"
            self.store.put("jobs", job["id"], job)
        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.background = [asyncio.create_task(self.scheduler()), asyncio.create_task(self.worker()),
                           asyncio.create_task(self.health_heartbeat())]

    async def on_ready(self):
        log.info("Argument Arena connected as %s", self.user)
        # A gateway reconnect does not reset participant deadlines. Core compensates
        # for missing heartbeat time before considering forfeits.
        for event in self.arena.recover():
            match = self.arena.get_match(event["match_id"])
            self.enqueue("notify", f"recovered:{match['id']}:{time.time_ns()}", match_id=match["id"],
                         text="The bot recovered from an interruption. Response deadlines were extended.")
        await self.recover_history()
        self._recovered = True

    async def on_disconnect(self):
        self._recovered = False
        self.health_path("arena-ready").unlink(missing_ok=True)

    async def on_resumed(self):
        await self.on_ready()

    @staticmethod
    def health_path(name):
        return Path(os.environ.get("HEALTH_DIRECTORY", "/tmp")) / name

    async def health_heartbeat(self):
        while not self.is_closed():
            now = str(time.time())
            self.health_path("arena-live").write_text(now)
            ready = self.health_path("arena-ready")
            if self.is_ready() and self._recovered:
                ready.write_text(now)
            else:
                ready.unlink(missing_ok=True)
            await asyncio.sleep(15)

    async def close(self):
        self.health_path("arena-ready").unlink(missing_ok=True)
        for task in self.background:
            task.cancel()
        if self.background:
            await asyncio.gather(*self.background, return_exceptions=True)
        await super().close()
        close = getattr(self.store, "close", None)
        if close:
            close()

    async def command_error(self, interaction, error):
        original = getattr(error, "original", error)
        if isinstance(original, (DomainError, ValueError, app_commands.CheckFailure)):
            await respond(interaction, str(original))
        elif isinstance(original, discord.Forbidden):
            await respond(interaction, "Discord denied the action. Check the bot's Administrator permission and configured channels.")
        else:
            log.exception("Application command failed", exc_info=original)
            await respond(interaction, "The action failed. Your stored match is preserved; check /match status before retrying.")

    def require_guild(self, interaction):
        if interaction.guild is None:
            raise DomainError("Use this command in your Discord server.")
        if self.config.guild_id and interaction.guild_id != self.config.guild_id:
            raise DomainError("This bot is configured for a different server.")
        return interaction.guild

    def staff(self, interaction) -> bool:
        self.require_guild(interaction)
        perms = interaction.user.guild_permissions
        if perms.administrator:
            return True
        role_ids = set(self.arena.server(interaction.guild_id).get("moderator_role_ids", []))
        return any(role.id in role_ids for role in interaction.user.roles)

    def require_staff(self, interaction):
        if not self.staff(interaction):
            raise DomainError("Only a configured moderator or server administrator may do that.")

    def checked_match(self, interaction, match_id: str | None, participant=False) -> dict:
        self.require_guild(interaction)
        if match_id is None:
            matches = self.store.list("matches", guild_id=interaction.guild_id, channel_id=interaction.channel_id)
            if not matches:
                raise DomainError("Provide a match ID or use the command in a match's main channel.")
            match = matches[-1]
        else:
            match = self.arena.get_match(match_id)
        if match["guild_id"] != interaction.guild_id:
            raise DomainError("That match belongs to another server.")
        if participant and interaction.user.id not in match["participants"]:
            raise DomainError("Only the two participants can perform that action.")
        return match

    async def accept_or_decline(self, interaction, match_id, action):
        async with self.match_locks[match_id]:
            match = self.checked_match(interaction, match_id, participant=True)
            method = self.arena.accept if action == "accept" else self.arena.decline
            match = method(match_id, interaction.user.id)
            if match["status"] == "ready":
                match = await self.ensure_channel(match)
            elif match.get("channel_id"):
                await self.apply_permissions(match)
            return match

    async def ensure_channel(self, match):
        guild = self.get_guild(match["guild_id"])
        if guild is None:
            raise DomainError("The server is unavailable. Channel creation will retry after reconnecting.")
        server = self.arena.server(guild.id)
        category = guild.get_channel(server.get("active_category_id", 0))
        if not isinstance(category, discord.CategoryChannel):
            raise DomainError("An administrator must configure /setup before starting a match.")
        members = {}
        for uid in match["participants"]:
            members[uid] = guild.get_member(uid)
            if members[uid] is None:
                try:
                    members[uid] = await guild.fetch_member(uid)
                except discord.NotFound as exc:
                    raise DomainError("A participant has left the server.") from exc
        marker = f"Argument Arena match {match['id']}"
        channel = guild.get_channel(match.get("channel_id", 0))
        if channel is None:
            channel = next((c for c in guild.text_channels if c.topic == marker), None)
        if channel is None:
            # Reconcile the API-side marker after a crash between creation and save.
            channel = next((c for c in await guild.fetch_channels()
                            if isinstance(c, discord.TextChannel) and c.topic == marker), None)
        if channel is None:
            name = server.get("channel_template", "match-{id}").format(id=match["id"], topic=match["topic"])
            name = re.sub(r"[^a-z0-9-]", "-", name.lower())[:90]
            channel = await guild.create_text_channel(
                name=name, category=category, topic=marker,
                overwrites=permission_overwrites(guild, match, server.get("moderator_role_ids", []), members=members),
                reason=f"Both participants accepted match {match['id']}",
            )
        match = self.arena.activate(match["id"], channel.id)
        await self.apply_permissions(match)
        if not match.get("opening_sent"):
            await channel.send(match_summary(match), allowed_mentions=discord.AllowedMentions(users=True))
            await channel.send("Accepted rules and feature settings:",
                               file=discord.File(io.BytesIO(json.dumps(match["settings"], indent=2).encode()),
                                                 filename="match-settings.json"))
            match = self.arena.get_match(match["id"])
            match["opening_sent"] = True
            self.store.put("matches", match["id"], match)
        await self.announce_to(server.get("announcement_channel_id"),
                               f"New debate: {match['topic']} — <#{channel.id}>")
        return match

    async def apply_permissions(self, match, closed=False, category_id=None):
        guild = self.get_guild(match["guild_id"])
        channel = guild.get_channel(match.get("channel_id", 0)) if guild else None
        if channel is None:
            return
        server = self.arena.server(guild.id)
        members = {}
        for uid in match["participants"]:
            member = guild.get_member(uid)
            if member is None:
                try:
                    member = await guild.fetch_member(uid)
                except discord.NotFound:
                    continue
            members[uid] = member
        kwargs = {"overwrites": permission_overwrites(guild, match, server.get("moderator_role_ids", []), closed, members),
                  "reason": f"Argument Arena match {match['id']} permissions"}
        if category_id:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                raise DomainError("The configured archive category is missing. Update /setup.")
            kwargs.update(category=category, sync_permissions=False)
        await channel.edit(**kwargs)
        self.store.put("discord_state", match["id"], {"fingerprint": self.permission_fingerprint(match), "closed": closed})
        if closed and match["settings"].get("archive_threads", False):
            for thread in channel.threads:
                await thread.edit(archived=True, locked=True, reason="Match closed")

    @staticmethod
    def permission_fingerprint(match):
        return hashlib.sha256(json.dumps({key: match.get(key) for key in
            ("status", "next_speaker_id", "settings", "channel_id")}, sort_keys=True).encode()).hexdigest()

    async def announce_to(self, channel_id, text):
        if channel_id:
            channel = self.get_channel(channel_id)
            if channel:
                for start in range(0, len(text), 1900):
                    await channel.send(text[start:start + 1900], suppress_embeds=True)

    async def announce(self, match, text):
        await self.announce_to(match.get("channel_id"), text)

    def enqueue(self, kind, key, **payload):
        job_id = f"{kind}:{key}"
        existing = self.store.get("jobs", job_id)
        if not existing or (existing["status"] == "failed" and existing.get("retry_at", 0) < time.time()):
            self.store.put("jobs", job_id, {"id": job_id, "kind": kind, "status": "pending",
                                           "attempts": 0, "created_at": time.time(), **payload})

    async def record_discord_message(self, message):
        if message.author.bot or message.guild is None or isinstance(message.channel, discord.Thread):
            return
        matches = self.store.list("matches", guild_id=message.guild.id, channel_id=message.channel.id)
        if not matches:
            return
        match = matches[-1]
        if match["status"] != "active" or message.author.id not in match["participants"]:
            return
        if self.store.get("messages", str(message.id)):
            return
        try:
            self.arena.record_message(match["id"], message.author.id, message.id,
                                               message.content, message.jump_url,
                                               now=message.created_at.timestamp())
        except DomainError as exc:
            await message.reply(str(exc), mention_author=False)
            return
        record = self.store.get("messages", str(message.id))
        if record:
            self.enqueue("analyze", str(message.id), match_id=match["id"], message_id=str(message.id))
        if self.arena.get_match(match["id"])["status"] == "judging":
            self.enqueue("judge", match["id"], match_id=match["id"])

    async def on_message(self, message):
        await self.record_discord_message(message)

    async def recover_history(self):
        for match in self.store.list("matches"):
            if match["status"] not in ("active", "paused", "judging", "ended"):
                continue
            channel = self.get_channel(match.get("channel_id", 0))
            if channel is None:
                continue
            records = {str(item["id"]): item for item in self.store.list("messages", match_id=match["id"])}
            try:
                # Reading the complete channel also catches edits/deletions made
                # during a process outage, which a fresh Gateway Identify cannot replay.
                history = [message async for message in channel.history(limit=None, oldest_first=True)]
            except discord.HTTPException:
                log.exception("Could not reconcile channel history for %s", match["id"])
                if match["status"] == "active":
                    self.arena.request_action(match["id"], 0, "pause", staff=True)
                    self.store.event(match["id"], "history_recovery_blocked", 0, {"action": "paused to avoid unfair forfeits"})
                continue
            observed = {str(message.id): message for message in history}
            for message_id, record in records.items():
                current = observed.get(message_id)
                if current is None and not record.get("deleted"):
                    await self.on_raw_message_delete(SimpleNamespace(message_id=int(message_id)))
                elif current is not None and current.content != record["content"]:
                    await self.on_raw_message_edit(SimpleNamespace(message_id=int(message_id), data={"content": current.content}))
            for message in history:
                if str(message.id) not in records:
                    await self.record_discord_message(message)

    def mark_result_stale(self, match_id):
        match = self.arena.get_match(match_id)
        if match.get("result"):
            match["result"]["evidence_stale"] = True
            self.store.put("matches", match_id, match)
            self.store.event(match_id, "result_evidence_changed", 0)

    async def on_raw_message_edit(self, payload):
        record = self.store.get("messages", str(payload.message_id))
        if not record or "content" not in payload.data:
            return
        record["revisions"] = record.get("revisions", []) + [{"content": record["content"], "at": time.time()}]
        record["content"] = payload.data["content"]
        record["edited_at"] = time.time()
        self.store.put("messages", record["id"], record)
        self.intelligence.invalidate_message(record["id"], content=record["content"])
        self.mark_result_stale(record["match_id"])
        self.invalidate_delivery(record["id"], record["match_id"])
        self.enqueue("analyze", f"{record['id']}:{len(record['revisions'])}",
                     match_id=record["match_id"], message_id=record["id"])

    async def on_raw_message_delete(self, payload):
        record = self.store.get("messages", str(payload.message_id))
        if record:
            record["deleted"] = True
            self.store.put("messages", record["id"], record)
            self.intelligence.invalidate_message(record["id"], deleted=True)
            self.mark_result_stale(record["match_id"])
            self.invalidate_delivery(record["id"], record["match_id"])

    def invalidate_delivery(self, message_id, match_id):
        published = False
        for item in self.store.list("analysis_outbox", match_id=match_id):
            if str(message_id) in item.get("message_versions", {}):
                published = published or item["status"] == "sent"
                item["status"] = "stale"
                self.store.put("analysis_outbox", item["id"], item)
        if published:
            self.enqueue("notify", f"stale:{message_id}:{time.time_ns()}", match_id=match_id,
                         text="An official message was edited or deleted. Its earlier claim analysis and research are stale; "
                              "use /match claims for refreshed evidence and /match review for any affected result.")

    async def on_raw_bulk_message_delete(self, payload):
        for message_id in payload.message_ids:
            await self.on_raw_message_delete(type("Deleted", (), {"message_id": message_id})())

    async def scheduler(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if self.is_ready() and self._recovered:
                try:
                    for event in self.arena.due():
                        match = self.arena.get_match(event["match_id"])
                        if event["kind"] == "recovered":
                            self.enqueue("notify", f"recovered:{match['id']}:{time.time_ns()}", match_id=match["id"],
                                         text="The bot recovered from an interruption. Response deadlines were extended.")
                except Exception:
                    log.exception("Could not process response deadlines")
                for match in self.store.list("matches"):
                    try:
                        await self.reconcile_match(match)
                    except (discord.HTTPException, DomainError):
                        log.exception("Could not reconcile match %s; other matches continue", match["id"])
                try:
                    await self.flush_analysis()
                except discord.HTTPException:
                    log.exception("Analysis delivery failed; reports remain pending")
            await asyncio.sleep(10)

    async def reconcile_match(self, match):
        if match["status"] == "ready" or (match["status"] == "active" and not match.get("opening_sent")):
            async with self.match_locks[match["id"]]:
                await self.ensure_channel(match)
        elif match["status"] in ("active", "paused"):
            state = self.store.get("discord_state", match["id"], {})
            if state.get("fingerprint") != self.permission_fingerprint(match):
                await self.apply_permissions(match)
            if match.get("reminded") and match.get("deadline"):
                self.enqueue("notify", f"reminder:{match['id']}:{match['deadline']}", match_id=match["id"],
                             text=f"Response reminder for <@{match['next_speaker_id']}>: deadline <t:{int(match['deadline'])}:F>.")
        elif match["status"] == "judging":
            self.enqueue("judge", match["id"], match_id=match["id"])
        elif match["status"] == "ended" and not match.get("discord_closed"):
            self.enqueue("close", match["id"], match_id=match["id"])

    async def worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if self.is_ready() and self._recovered:
                jobs = sorted(self.store.list("jobs", status="pending"), key=lambda j: j["created_at"])
                for job in jobs:
                    if job.get("retry_at", 0) > time.time():
                        continue
                    job["status"] = "running"
                    job["attempts"] += 1
                    self.store.put("jobs", job["id"], job)
                    try:
                        await self.process_job(job)
                        job["status"] = "done"
                    except JobDeferred as exc:
                        job["status"] = "pending"
                        job["attempts"] -= 1
                        job["retry_at"] = time.time() + exc.delay
                    except asyncio.CancelledError:
                        job["status"] = "pending"
                        self.store.put("jobs", job["id"], job)
                        raise
                    except Exception as exc:
                        log.exception("Background job failed: %s", job["id"])
                        job["status"] = "failed" if job["attempts"] >= 3 else "pending"
                        job["error"] = type(exc).__name__
                        job["retry_at"] = time.time() + 30 * job["attempts"]
                    self.store.put("jobs", job["id"], job)
            await asyncio.sleep(1)

    async def process_job(self, job):
        match = self.arena.get_match(job["match_id"])
        if job["kind"] == "analyze":
            message = self.store.get("messages", str(job["message_id"]))
            if not message or message.get("deleted"):
                return
            report = await self.intelligence.analyze_message(match, message)
            report.setdefault("author_id", message["author_id"])
            if report:
                for claim in report.get("claims", []):
                    if claim.get("check_status") == "pending" and claim.get("kind") == "empirical":
                        self.enqueue("check", claim.get("storage_key", claim["id"]), match_id=match["id"],
                                     claim_id=claim.get("storage_key", claim["id"]))
                await self.publish_analysis(match, report)
                if match["settings"].get("live_scores"):
                    live = await self.intelligence.judge(match, self.store.list("messages", match_id=match["id"]),
                                                        self.store.list("claims", match_id=match["id"]), provisional=True)
                    await self.publish_analysis(match, {"provisional_scores": live})
        elif job["kind"] == "check":
            claim = self.store.get("claims", job["claim_id"])
            if claim and claim.get("check_status") != "stale":
                report = await self.intelligence.check_claim(match, claim, sources=job.get("sources"))
                await self.publish_analysis(match, report, force=bool(job.get("requested_by")))
        elif job["kind"] == "notify":
            await self.announce(match, job["text"])
        elif job["kind"] == "profile":
            report = await self.profiles.refresh(match)
            if any(item.get("status") == "analysis_unavailable" for item in report.get("updated", [])):
                raise JobDeferred("Profile provider unavailable; retrying later.", delay=300)
        elif job["kind"] == "judge":
            if match["status"] != "judging":
                return
            pending = [j for j in self.store.list("jobs", match_id=match["id"])
                       if j["kind"] in ("analyze", "check") and j["status"] in ("pending", "running")]
            if pending:
                job["status"] = "pending"
                raise JobDeferred("Waiting for pending match evidence.")
            report = await self.intelligence.judge(
                match, self.store.list("messages", match_id=match["id"]),
                self.store.list("claims", match_id=match["id"]),
            )
            if report.get("status") == "stale":
                raise JobDeferred("The transcript changed; waiting for refreshed analysis.")
            self.arena.end(match["id"], report.get("outcome", "inconclusive"),
                           winner_id=report.get("winner_id"), report=report)
        elif job["kind"] == "close":
            await self.close_match(match)
        else:
            raise DomainError("Unknown background job.")

    async def publish_analysis(self, match, report, force=False):
        match = self.arena.get_match(match["id"])
        if not report or report.get("status") in ("ignored", "disabled", "stale"):
            return
        report = json.loads(json.dumps(report, default=str))
        if isinstance(report.get("feedback"), list):
            report["feedback"] = [item for item in report["feedback"] if match["settings"].get(item.get("kind"), False)]
        if "correction" in report:
            report["correction"] = bool(report["correction"] and match["settings"].get("factual_corrections")
                and match["settings"].get("background_research")
                and report.get("confidence", 0) >= match["settings"].get("correction_confidence", 0.85))
        author = report.get("author_id")
        if match["settings"].get("coaching_delivery", "private") == "private" and author:
            private = [item for item in report.get("feedback", []) if item.get("kind") == "coaching"]
            if private:
                self.queue_report(match, {"coaching": private, "source_message_id": report.get("id")}, recipient_id=author)
            if isinstance(report.get("feedback"), list):
                report["feedback"] = [item for item in report["feedback"] if item.get("kind") != "coaching"]
        if not match["settings"].get("claim_tracking", True):
            report.pop("claims", None)
            if "check_status" in report and not force and not report.get("correction"):
                return
        if (not report.get("claims") and not report.get("feedback") and not report.get("clarifications")
                and report.get("status") == "complete" and "verdict" not in report and "provisional_scores" not in report):
            return
        self.queue_report(match, report, force=force)

    def queue_report(self, match, report, recipient_id=None, force=False):
        key = f"{match['id']}:{time.time_ns()}"
        message_ids = {str(report.get(field)) for field in ("id", "message_id", "source_message_id") if report.get(field)}
        message_ids.update(str(claim.get("message_id")) for claim in report.get("claims", []))
        if "provisional_scores" in report:
            message_ids.update(str(message["id"]) for message in self.store.list("messages", match_id=match["id"]))
        versions = {}
        for message_id in message_ids:
            message = self.store.get("messages", message_id)
            if message:
                versions[message_id] = hashlib.sha256(message["content"].encode()).hexdigest()
        self.store.put("analysis_outbox", key, {"id": key, "match_id": match["id"], "report": report,
                                               "recipient_id": recipient_id, "created_at": time.time(), "status": "pending",
                                               "message_versions": versions, "force": force})

    async def send_report(self, destination, heading, report):
        body = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if len(body) + len(heading) <= 1850:
            await destination.send(heading + "\n" + body, suppress_embeds=True)
        else:
            await destination.send(heading, file=discord.File(io.BytesIO(body.encode()), filename="arena-report.json"))

    async def flush_analysis(self, force_match_id=None):
        pending = defaultdict(list)
        for item in self.store.list("analysis_outbox", status="pending"):
            pending[(item["match_id"], item.get("recipient_id"))].append(item)
        for (match_id, recipient), items in pending.items():
            match = self.arena.get_match(match_id)
            interval = match["settings"].get("notification_interval", 60)
            if force_match_id != match_id and time.time() - min(i["created_at"] for i in items) < interval:
                continue
            valid = []
            for item in items:
                report = json.loads(json.dumps(item["report"]))
                stale = False
                for message_id, digest in item.get("message_versions", {}).items():
                    message = self.store.get("messages", message_id)
                    if not message or message.get("deleted") or hashlib.sha256(message["content"].encode()).hexdigest() != digest:
                        stale = True
                if report.get("storage_key"):
                    claim = self.store.get("claims", report["storage_key"], {})
                    if claim.get("check_status") == "stale" or claim.get("checked_at") != report.get("checked_at"):
                        stale = True
                if "coaching" in report and not match["settings"].get("coaching"):
                    stale = True
                if isinstance(report.get("feedback"), list):
                    report["feedback"] = [feedback for feedback in report["feedback"]
                        if match["settings"].get(feedback.get("kind"), False) and
                        (feedback.get("kind") != "coaching" or recipient or match["settings"].get("coaching_delivery") == "public")]
                if not recipient and not match["settings"].get("claim_tracking", True):
                    report.pop("claims", None)
                if "correction" in report:
                    report["correction"] = bool(report["correction"] and match["settings"].get("factual_corrections")
                        and match["settings"].get("background_research")
                        and report.get("confidence", 0) >= match["settings"].get("correction_confidence", 0.85))
                    if not match["settings"].get("claim_tracking", True) and not report["correction"] and not item.get("force"):
                        stale = True
                if "provisional_scores" in report:
                    if not match["settings"].get("live_scores"):
                        stale = True
                    elif match["settings"].get("feedback_delivery", "private") == "private":
                        report["provisional_scores"].pop("feedback", None)
                if stale:
                    item["status"] = "stale"
                    self.store.put("analysis_outbox", item["id"], item)
                else:
                    item["report"] = report
                    valid.append(item)
            items = valid
            if not items:
                continue
            destination = self.get_channel(match.get("channel_id", 0))
            if recipient:
                destination = self.get_user(recipient) or await self.fetch_user(recipient)
            if not destination:
                continue
            try:
                # Bound an attachment even when an outage accumulates many reports.
                batch = items[:20]
                await self.send_report(destination, "LLM assistance (reviewable, with source links where available):",
                                       [item["report"] for item in batch])
            except discord.Forbidden:
                if recipient:
                    for item in items:
                        item["status"] = "delivery_blocked"
                        self.store.put("analysis_outbox", item["id"], item)
                    await self.announce(match, "Private coaching could not be delivered. Enable server-member DMs; "
                                              "private content was withheld from the public channel.")
                    continue
                raise
            for item in batch:
                item["status"] = "sent"
                self.store.put("analysis_outbox", item["id"], item)

    async def close_match(self, match):
        if match["status"] != "ended":
            return
        expected_result = json.loads(json.dumps(match.get("result")))
        server = self.arena.server(match["guild_id"])
        outcome = match.get("result", {}).get("outcome", "")
        category_key = ("cancelled_category_id" if outcome == "cancelled" else
                        "forfeited_category_id" if "forfeit" in outcome else "completed_category_id")
        category_id = server.get(category_key) if match["settings"].get("automatic_archival", True) else None
        await self.apply_permissions(match, closed=True, category_id=category_id)
        await self.flush_analysis(force_match_id=match["id"])
        channel = self.get_channel(match.get("channel_id", 0))
        if channel and not match.get("result_published"):
            result = match.get("result", {})
            await channel.send(f"Match ended: {result.get('outcome', 'recorded')}. "
                               f"Winner: {result.get('winner_id') or 'none'}. Use /match result for the report.")
            report = match.get("result", {}).get("report")
            if report:
                report = json.loads(json.dumps(report))
                if match["settings"].get("feedback_delivery", "private") == "private":
                    feedback = report.pop("feedback", {})
                    if isinstance(feedback, dict):
                        for uid in match["participants"]:
                            personal = feedback.get(str(uid))
                            if personal:
                                user = self.get_user(uid) or await self.fetch_user(uid)
                                try:
                                    await self.send_report(user, f"Private feedback for match {match['id']}", personal)
                                except discord.Forbidden:
                                    await self.announce(match, "A participant's DMs blocked private feedback. "
                                                              "It remains available to that participant through /match result.")
                await channel.send(file=discord.File(io.BytesIO(json.dumps(report, indent=2, ensure_ascii=False).encode()),
                                                     filename="judging-report.json"))
            await self.announce_to(server.get("results_channel_id"), match_summary(match))
            current = self.arena.get_match(match["id"])
            if current.get("result") != expected_result:
                raise JobDeferred("Result changed while publishing; reconciling the new result.")
            current["result_published"] = True
            self.store.put("matches", current["id"], current)
        self.enqueue("profile", match["id"], match_id=match["id"])
        match = self.arena.get_match(match["id"])
        if match.get("result") != expected_result:
            raise JobDeferred("Result changed while closing; reconciling the new result.")
        match["discord_closed"] = True
        self.store.put("matches", match["id"], match)


class ArenaCommands(commands.Cog):
    match = app_commands.Group(name="match", description="Create, manage and review debates", guild_only=True)
    settings = app_commands.Group(name="settings", description="Server administration", guild_only=True)
    profile = app_commands.Group(name="profile", description="Profiles and privacy", guild_only=True)
    train = app_commands.Group(name="train", description="Practice reasoning and fallacies", guild_only=True)

    def __init__(self, bot: ArenaBot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check whether Argument Arena is online")
    async def ping(self, interaction: discord.Interaction):
        self.bot.require_guild(interaction)
        await respond(interaction, f"Pong! Gateway latency: {self.bot.latency * 1000:.0f} ms.")

    @app_commands.command(name="setup", description="Configure debate categories, result channels and moderators")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction,
                    active: discord.CategoryChannel, completed: discord.CategoryChannel,
                    forfeited: discord.CategoryChannel, cancelled: discord.CategoryChannel,
                    moderator: discord.Role | None = None,
                    results: discord.TextChannel | None = None,
                    announcements: discord.TextChannel | None = None):
        guild = self.bot.require_guild(interaction)
        if not interaction.user.guild_permissions.administrator:
            raise DomainError("Only a server administrator can configure the bot.")
        if not guild.me.guild_permissions.administrator:
            raise DomainError("Install the bot with Administrator permission before running /setup.")
        config = self.bot.arena.configure(
            guild.id, interaction.user.id,
            active_category_id=active.id, completed_category_id=completed.id,
            forfeited_category_id=forfeited.id, cancelled_category_id=cancelled.id,
            moderator_role_ids=[moderator.id] if moderator else [],
            results_channel_id=results.id if results else None,
            announcement_channel_id=announcements.id if announcements else None,
        )
        await respond(interaction, "Server configured.", data=config)

    @settings.command(name="server", description="View server configuration or change it using JSON")
    async def server_settings(self, interaction: discord.Interaction, patch: str | None = None):
        self.bot.require_staff(interaction)
        config = (self.bot.arena.configure(interaction.guild_id, interaction.user.id, **parse_patch(patch))
                  if patch else self.bot.arena.server(interaction.guild_id))
        await respond(interaction, "Server settings. Credentials are supplied through deployment secrets.", data=config)

    @match.command(name="options", description="List all optional feature toggles and their default parameters")
    async def options(self, interaction: discord.Interaction):
        from .core import DEFAULT_SETTINGS, PRESETS
        self.bot.require_guild(interaction)
        await respond(interaction, "Every boolean is an explicit on/off switch. Use /match settings patch to propose values.",
                      data={"defaults": DEFAULT_SETTINGS, "presets": PRESETS})

    @match.command(name="challenge", description="Challenge a member to a debate from a channel or thread")
    async def challenge(self, interaction: discord.Interaction, member: discord.Member, topic: str,
                        your_position: str = "For", their_position: str = "Against", preset: str = "casual"):
        self.bot.require_guild(interaction)
        if member.bot:
            raise DomainError("Challenge a human member; use /train start for bot battles.")
        await interaction.response.defer()
        origin_url = (f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}")
        match = self.bot.arena.challenge(
            interaction.guild_id, interaction.user.id, member.id, topic,
            positions={str(interaction.user.id): your_position, str(member.id): their_position},
            origin_url=origin_url, preset=preset,
        )
        view = MatchView(self.bot, match["id"])
        self.bot.add_view(view)
        await respond(interaction, match_summary(match) + "\nReview /match settings before accepting.",
                      data=match["settings"], ephemeral=False, view=view)

    @match.command(name="accept", description="Accept the currently proposed match rules")
    async def accept(self, interaction: discord.Interaction, match_id: str):
        self.bot.checked_match(interaction, match_id, participant=True)
        await interaction.response.defer(ephemeral=True)
        match = await self.bot.accept_or_decline(interaction, match_id, "accept")
        await respond(interaction, match_summary(match))

    @match.command(name="decline", description="Decline a pending challenge")
    async def decline(self, interaction: discord.Interaction, match_id: str):
        self.bot.checked_match(interaction, match_id, participant=True)
        await interaction.response.defer(ephemeral=True)
        match = await self.bot.accept_or_decline(interaction, match_id, "decline")
        await respond(interaction, match_summary(match))

    @match.command(name="settings", description="View every feature toggle or propose a JSON settings change")
    async def match_settings(self, interaction: discord.Interaction, match_id: str | None = None,
                             patch: str | None = None):
        match = self.bot.checked_match(interaction, match_id, participant=bool(patch))
        if patch:
            await interaction.response.defer(ephemeral=True)
            match = self.bot.arena.propose_settings(match["id"], interaction.user.id, parse_patch(patch))
            await self.bot.announce(match, "Settings changes proposed. Both participants must review and /match accept.")
        await respond(interaction, "All feature switches and parameters. Submit changed keys as JSON; "
                      "accepted rules require agreement from both participants.",
                      data={"current": match["settings"], "proposal": match.get("settings_proposal"),
                            "confirmations": match.get("confirmations", [])},
                      view=MatchView(self.bot, match["id"]))

    @match.command(name="status", description="Show participants, turn, response deadline and match state")
    async def status(self, interaction: discord.Interaction, match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id)
        await respond(interaction, match_summary(match), data=match.get("action_proposal"))

    @match.command(name="submit", description="Submit your completed turn and start the opponent's clock")
    async def submit(self, interaction: discord.Interaction, match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id, participant=True)
        await interaction.response.defer(ephemeral=True)
        match = self.bot.arena.submit(match["id"], interaction.user.id)
        await self.bot.apply_permissions(match)
        await respond(interaction, match_summary(match))
        await self.bot.announce(match, match_summary(match))

    @match.command(name="claims", description="List attributed claims, source links and current research states")
    async def claims(self, interaction: discord.Interaction, match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id)
        if not match["settings"].get("claim_tracking", True) and interaction.user.id not in match["participants"] and not self.bot.staff(interaction):
            raise DomainError("The public claim ledger is disabled for this match.")
        await respond(interaction, "Claim ledger (research failures do not establish falsity).",
                      data=self.bot.store.list("claims", match_id=match["id"]))

    def claim_for(self, match, claim_id):
        claim = self.bot.store.get("claims", f"{match['id']}:{claim_id}")
        if not claim:
            claim = next((c for c in self.bot.store.list("claims", match_id=match["id"])
                          if c["id"] == claim_id), None)
        if claim is None:
            raise DomainError("That claim does not exist in this match. Use /match claims.")
        return claim

    @match.command(name="check", description="Queue an on-demand evidence-based check or recheck")
    async def check(self, interaction: discord.Interaction, claim_id: str, match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id, participant=True)
        if not match["settings"].get("on_demand_checks", True):
            raise DomainError("On-demand checking is disabled for this match.")
        claim = self.claim_for(match, claim_id)
        if match.get("on_demand_checks_used", 0) >= match["settings"].get("on_demand_limit", 5):
            raise DomainError("This match has reached its agreed on-demand research limit.")
        if claim.get("check_status") == "stale":
            raise DomainError("This claim's message changed. Wait for refreshed claim extraction.")
        match["on_demand_checks_used"] = match.get("on_demand_checks_used", 0) + 1
        self.bot.store.put("matches", match["id"], match)
        self.bot.enqueue("check", f"{match['id']}:{claim_id}:{interaction.id}", match_id=match["id"], requested_by=interaction.user.id,
                         claim_id=claim.get("storage_key", claim["id"]), sources=claim.get("submitted_sources") or None)
        await respond(interaction, f"Research queued for {claim_id}. Pending work and budgets appear in /match claims.")

    @match.command(name="source", description="Submit an evidence URL for a claim and queue a recheck")
    async def source(self, interaction: discord.Interaction, claim_id: str, url: str,
                     match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id, participant=True)
        claim = self.claim_for(match, claim_id)
        if not url.startswith("https://") or len(url) > 2000:
            raise DomainError("Provide a public HTTPS source URL.")
        sources = claim.get("submitted_sources", [])
        if len(sources) >= 10:
            raise DomainError("A claim can have at most ten member-submitted sources.")
        if url not in sources:
            claim["submitted_sources"] = sources + [url]
            self.bot.store.put("claims", claim.get("storage_key", claim["id"]), claim)
            self.bot.store.event(match["id"], "source_submitted", interaction.user.id,
                                 {"claim_id": claim_id, "url": url})
        await respond(interaction, "Source recorded. Use /match check to research it under the match's checking rules.")

    @match.command(name="dispute", description="Record a claim interpretation or result dispute for staff review")
    async def dispute(self, interaction: discord.Interaction, target: str, reason: str,
                      match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id, participant=True)
        if len(reason) < 10 or len(reason) > 2000:
            raise DomainError("Explain the dispute in 10 to 2000 characters.")
        if target != "result":
            self.claim_for(match, target)
        self.bot.store.event(match["id"], "dispute", interaction.user.id, {"target": target, "reason": reason})
        await respond(interaction, "Dispute recorded for moderator review.")
        await self.bot.announce(match, f"A participant disputed {target}. Staff can use /match review.")

    async def action(self, interaction, match_id, action, **params):
        match = self.bot.checked_match(interaction, match_id)
        staff = self.bot.staff(interaction)
        if interaction.user.id not in match["participants"] and not staff:
            raise DomainError("Only participants and configured moderators can manage this match.")
        await interaction.response.defer(ephemeral=True)
        match = self.bot.arena.request_action(match["id"], interaction.user.id, action, staff=staff, **params)
        if match.get("channel_id"):
            await self.bot.apply_permissions(match, closed=match["status"] == "ended")
        await respond(interaction, match_summary(match), data=match.get("action_proposal"))
        await self.bot.announce(match, f"{action.replace('_', ' ').capitalize()} updated.\n" + match_summary(match))
        if match["status"] == "judging":
            self.bot.enqueue("judge", match["id"], match_id=match["id"])
        elif match["status"] == "ended":
            self.bot.enqueue("close", match["id"], match_id=match["id"])

    @match.command(name="pause", description="Request a mutually agreed pause, or pause as staff")
    async def pause(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "pause")

    @match.command(name="resume", description="Agree to resume a paused debate, or resume as staff")
    async def resume(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "resume")

    @match.command(name="extend", description="Propose an extension in hours, or grant one as staff")
    async def extend(self, interaction: discord.Interaction, hours: float, match_id: str | None = None):
        await self.action(interaction, match_id, "extend", hours=hours)

    @match.command(name="request", description="Set an explicit next speaker in a flexible-order match")
    async def request_response(self, interaction: discord.Interaction, member: discord.Member,
                               match_id: str | None = None):
        await self.action(interaction, match_id, "request_response", user_id=member.id)

    @match.command(name="concede", description="Concede this match to the other participant")
    async def concede(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "concede")

    @match.command(name="draw", description="Propose or accept an agreed draw")
    async def draw(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "draw")

    @match.command(name="finish", description="Agree to finish and run the enabled final judging")
    async def finish(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "finish")

    @match.command(name="cancel", description="Request mutual cancellation, or cancel as staff")
    async def cancel(self, interaction: discord.Interaction, match_id: str | None = None):
        await self.action(interaction, match_id, "cancel")

    @match.command(name="result", description="Retrieve a finished match's result, evidence and feedback")
    async def result(self, interaction: discord.Interaction, match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id)
        if not match.get("result"):
            raise DomainError("This match does not have a recorded result yet.")
        votes = self.bot.store.list("votes", match_id=match["id"])
        counts = {str(uid): sum(v["candidate_id"] == uid for v in votes) for uid in match["participants"]}
        result = json.loads(json.dumps(match["result"]))
        if match["settings"].get("feedback_delivery", "private") == "private" and isinstance(result.get("report"), dict):
            feedback = result["report"].pop("feedback", {})
            if interaction.user.id in match["participants"] and isinstance(feedback, dict):
                result["report"]["your_feedback"] = feedback.get(str(interaction.user.id), {})
        await respond(interaction, match_summary(match),
                      data={"official_result": result, "audience_vote_separate": counts})

    @match.command(name="archive", description="Manually organize a finished match (moderators only)")
    async def archive(self, interaction: discord.Interaction, match_id: str | None = None):
        self.bot.require_staff(interaction)
        match = self.bot.checked_match(interaction, match_id)
        if match["status"] != "ended":
            raise DomainError("Only a finished match can be archived.")
        await interaction.response.defer(ephemeral=True)
        outcome = match.get("result", {}).get("outcome", "")
        key = ("cancelled_category_id" if outcome == "cancelled" else
               "forfeited_category_id" if "forfeit" in outcome else "completed_category_id")
        category = self.bot.arena.server(interaction.guild_id).get(key)
        await self.bot.apply_permissions(match, closed=True, category_id=category)
        self.bot.store.event(match["id"], "manual_archive", interaction.user.id, {"category_id": category})
        await respond(interaction, "Match archived with audience and posting permissions preserved.")

    @match.command(name="vote", description="Cast an audience vote; it does not affect the official result")
    async def vote(self, interaction: discord.Interaction, member: discord.Member,
                   match_id: str | None = None):
        match = self.bot.checked_match(interaction, match_id)
        if not match["settings"].get("audience_voting", False):
            raise DomainError("Audience voting is disabled for this match.")
        eligibility = match["settings"].get("audience_eligibility", "nonparticipants")
        if interaction.user.bot or (eligibility == "nonparticipants" and interaction.user.id in match["participants"]):
            raise DomainError("You are not eligible under this match's audience-voting rules.")
        if member.id not in match["participants"]:
            raise DomainError("Vote for one of the two participants.")
        if match["status"] not in ("active", "paused", "judging"):
            raise DomainError("Audience voting is closed.")
        closes_at = match.get("started_at", match["created_at"]) + match["settings"].get("audience_vote_hours", 24) * 3600
        if time.time() > closes_at:
            raise DomainError("The agreed audience-voting window has closed.")
        channel = interaction.guild.get_channel(match.get("channel_id", 0))
        if channel is None or not channel.permissions_for(interaction.user).view_channel:
            raise DomainError("Only members who can view the match may cast audience votes.")
        key = f"{match['id']}:{interaction.user.id}"
        self.bot.store.put("votes", key, {"id": key, "match_id": match["id"], "guild_id": interaction.guild_id,
                                         "user_id": interaction.user.id, "candidate_id": member.id})
        await respond(interaction, "Audience vote recorded separately from judging and ratings.")

    @match.command(name="review", description="Review match events and optionally request a fresh judgment (staff)")
    async def review(self, interaction: discord.Interaction, match_id: str, rejudge: bool = False):
        self.bot.require_staff(interaction)
        match = self.bot.checked_match(interaction, match_id)
        await interaction.response.defer(ephemeral=True)
        data = {"match": match, "events": self.bot.store.list("events", match_id=match["id"])}
        if rejudge:
            report = await self.bot.intelligence.judge(
                match, self.bot.store.list("messages", match_id=match["id"]),
                self.bot.store.list("claims", match_id=match["id"]),
            )
            self.bot.store.event(match["id"], "staff_rejudge", interaction.user.id, report)
            data["proposed_judgment"] = report
        await respond(interaction, "Staff review. A new judgment is a proposal until /match correct records a correction.", data=data)

    @match.command(name="correct", description="Correct a finished result and recompute affected ratings (staff)")
    async def correct(self, interaction: discord.Interaction, match_id: str, reason: str,
                      winner: discord.Member | None = None):
        self.bot.require_staff(interaction)
        match = self.bot.checked_match(interaction, match_id)
        match = self.bot.arena.correct_result(match["id"], interaction.user.id, winner.id if winner else None, reason)
        match["discord_closed"] = False
        self.bot.store.put("matches", match["id"], match)
        self.bot.enqueue("close", f"{match['id']}:{interaction.id}", match_id=match["id"])
        await respond(interaction, "Result corrected; downstream ratings rebuilt.", data=match.get("result"))
        await self.bot.announce(match, "Staff corrected the recorded result. Reason: " + reason)

    @app_commands.command(name="leaderboard", description="Show ranked ratings and competitive records")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction, topic: str | None = None,
                          days: app_commands.Range[int, 1, 3650] | None = None,
                          preset: str | None = None, min_matches: app_commands.Range[int, 1, 1000] = 1):
        self.bot.require_guild(interaction)
        since = time.time() - days * 86400 if days else None
        await respond(interaction, "Ranked leaderboard. Casual matches and training are separate.",
                      data=self.bot.arena.leaderboard(interaction.guild_id, topic=topic, since=since,
                                                     preset=preset, min_matches=min_matches))

    @profile.command(name="view", description="View a member's debate record and available opted-in insights")
    async def profile_view(self, interaction: discord.Interaction, member: discord.Member | None = None):
        self.bot.require_guild(interaction)
        await interaction.response.defer(ephemeral=True)
        await respond(interaction, "Debate profile", data=await self.bot.profiles.view(
            interaction.guild_id, (member or interaction.user).id, interaction.user.id))

    @profile.command(name="settings", description="Choose profile analysis consent, visibility and recommendations")
    async def profile_settings(self, interaction: discord.Interaction, patch: str | None = None):
        self.bot.require_guild(interaction)
        data = self.bot.profiles.settings(interaction.guild_id, interaction.user.id,
                                         parse_patch(patch) if patch else None)
        await respond(interaction, "Your profile preferences", data=data)

    @profile.command(name="remove-insights", description="Delete generated insights and stop future analysis")
    async def remove_insights(self, interaction: discord.Interaction):
        self.bot.require_guild(interaction)
        self.bot.profiles.remove_insights(interaction.guild_id, interaction.user.id)
        await respond(interaction, "Your generated profile insights were removed and future analysis was disabled.")

    @profile.command(name="dispute", description="Record a correction request about your generated profile")
    async def profile_dispute(self, interaction: discord.Interaction, explanation: str, insight_id: str | None = None):
        self.bot.require_guild(interaction)
        if not 10 <= len(explanation) <= 2000:
            raise DomainError("Explain the correction in 10 to 2000 characters.")
        if insight_id:
            self.bot.profiles.settings(interaction.guild_id, interaction.user.id, {"correction": {"insight_id": insight_id, "text": explanation}})
        key = f"{interaction.guild_id}:{interaction.user.id}:{interaction.id}"
        self.bot.store.put("profile_disputes", key, {"id": key, "guild_id": interaction.guild_id,
                                                    "user_id": interaction.user.id, "explanation": explanation,
                                                    "created_at": time.time(), "status": "open"})
        await respond(interaction, "Correction request recorded. You can hide or remove insights while it is reviewed.")

    @train.command(name="start", description="Start a fallacy puzzle, repair exercise or training battle")
    @app_commands.choices(mode=[app_commands.Choice(name=n, value=v) for n, v in (
        ("Spot the fallacy", "spot"), ("Mixed puzzles", "mixed"), ("Repair the argument", "repair"),
        ("Sound or fallacious", "sound"), ("Training battle", "battle"), ("Personalized review", "personalized"),
    )])
    async def train_start(self, interaction: discord.Interaction, mode: str = "spot",
                          difficulty: str = "normal", topic: str | None = None):
        self.bot.require_guild(interaction)
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.training.start(interaction.guild_id, interaction.user.id,
                                               mode=mode, difficulty=difficulty, topic=topic)
        await respond(interaction, "Training exercise. Use /train answer or /train hint.", data=result)

    @train.command(name="fallacy", description="Practice a specific fallacy with an original exercise")
    async def train_fallacy(self, interaction: discord.Interaction, name: str,
                            difficulty: str = "normal", topic: str | None = None):
        self.bot.require_guild(interaction)
        await interaction.response.defer(ephemeral=True)
        result = await self.bot.training.start(interaction.guild_id, interaction.user.id,
                                               mode="chosen", fallacy=name, difficulty=difficulty, topic=topic)
        await respond(interaction, "Focused practice. Use /train answer or /train hint.", data=result)

    @train.command(name="answer", description="Explain the reasoning error, repair it or take your battle turn")
    async def train_answer(self, interaction: discord.Interaction, text: str):
        self.bot.require_guild(interaction)
        await interaction.response.defer(ephemeral=True)
        await respond(interaction, "Training feedback", data=await self.bot.training.answer(
            interaction.guild_id, interaction.user.id, text))

    @train.command(name="hint", description="Get a hint for your active training exercise")
    async def train_hint(self, interaction: discord.Interaction):
        self.bot.require_guild(interaction)
        await interaction.response.defer(ephemeral=True)
        await respond(interaction, "Hint", data=await self.bot.training.hint(interaction.guild_id, interaction.user.id))

    @train.command(name="progress", description="View accuracy, explanation scores and recommended practice")
    async def train_progress(self, interaction: discord.Interaction):
        self.bot.require_guild(interaction)
        await respond(interaction, "Your training progress", data=self.bot.training.progress(
            interaction.guild_id, interaction.user.id))
