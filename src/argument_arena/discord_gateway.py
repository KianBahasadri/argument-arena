"""Discord side effects, permission policy, recovery and retryable deliveries."""

import hashlib
import json
from datetime import UTC, datetime

import discord

from argument_arena.providers import ProviderError
from argument_arena.settings import ArenaError


def overwrites(guild, match, config, members, bot_member, closed=False):
    settings = match["settings"]
    thread_open = settings["threads"]["enabled"] and not (
        closed and (settings["threads"]["close_after"] or settings["archive"]["lock_threads"])
    )
    common = dict(
        view_channel=True,
        read_message_history=True,
        send_messages=False,
        add_reactions=settings["reactions"]["enabled"],
        create_public_threads=thread_open and settings["threads"]["create"],
        create_private_threads=False,
        send_messages_in_threads=thread_open,
        use_application_commands=True,
        send_tts_messages=False,
        manage_channels=False,
        manage_webhooks=False,
        manage_messages=False,
        manage_threads=False,
    )
    # A role-level allow overrides @everyone's deny. Deny posting on EVERY ordinary role.
    result = {role: discord.PermissionOverwrite(**common) for role in guild.roles}
    for role in guild.roles:
        if str(role.id) in config["moderator_roles"]:
            result[role].send_messages = True
            result[role].manage_messages = True
            result[role].manage_channels = True
            result[role].manage_webhooks = True
            result[role].manage_threads = True
    for member in members:
        staff = any(str(r.id) in config["moderator_roles"] for r in getattr(member, "roles", []))
        result[member] = discord.PermissionOverwrite(
            **{
                **common,
                "send_messages": staff or (not closed and match["state"] == "active"),
                "manage_channels": staff,
                "manage_webhooks": staff,
                "manage_messages": staff,
                "manage_threads": staff,
            }
        )
    result[bot_member] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        manage_messages=True,
        manage_channels=True,
        manage_threads=True,
        send_messages_in_threads=True,
        create_public_threads=True,
        add_reactions=True,
        attach_files=True,
    )
    return result


class DiscordGateway:
    def __init__(self, client, arena):
        self.client, self.arena, self.repo = client, arena, arena.repo

    def guild(self, guild_id):
        guild = self.client.get_guild(int(guild_id))
        if guild is None or guild.me is None:
            raise ProviderError("guild_unavailable")
        return guild

    async def channel(self, channel_id):
        if not channel_id:
            raise ProviderError("channel_not_created")
        return self.client.get_channel(int(channel_id)) or await self.client.fetch_channel(
            int(channel_id)
        )

    async def create(self, job):
        match = await self.repo.match(job["match_id"])
        if match["state"] != "starting":
            return
        config = await self.arena.config(match["guild"])
        guild = self.guild(match["guild"])
        marker = f"Argument Arena match:{match['id']}"
        # Query the server on every uncertain retry; the cache can lag a successful create.
        channels = await guild.fetch_channels()
        existing = next(
            (c for c in channels if isinstance(c, discord.TextChannel) and c.topic == marker), None
        )
        if existing is None:
            category = guild.get_channel(int(config["categories"]["active"]))
            if not isinstance(category, discord.CategoryChannel):
                raise ProviderError("active_category_unavailable", retry=False)
            members = [
                guild.get_member(int(p)) or await guild.fetch_member(int(p))
                for p in match["players"]
            ]
            permissions = overwrites(guild, {**match, "state": "active"}, config, members, guild.me)
            existing = await guild.create_text_channel(
                config["channel_name"].replace("{id}", match["id"]),
                category=category,
                topic=marker,
                overwrites=permissions,
                reason=f"Accepted debate {match['id']}",
            )
        await self.arena.attach_channel(match["id"], str(existing.id))

    async def archive(self, job):
        match = await self.repo.match(job["match_id"])
        if match["state"] != "closed" or not match["channel"]:
            return
        config = await self.arena.config(match["guild"])
        result = await self.arena.result(match["id"], match["guild"])
        guild, channel = self.guild(match["guild"]), await self.channel(match["channel"])
        members = []
        for player in match["players"]:
            try:
                members.append(
                    guild.get_member(int(player)) or await guild.fetch_member(int(player))
                )
            except discord.NotFound:
                pass
        permissions = overwrites(guild, match, config, members, guild.me, closed=True)
        args = {
            "overwrites": permissions,
            "sync_permissions": False,
            "reason": f"Closed debate {match['id']}",
        }
        if job["data"].get("move"):
            route = {"forfeit": "forfeited", "cancelled": "cancelled"}.get(
                result["outcome"], "completed"
            )
            category_id = config["categories"][route]
            if category_id:
                category = guild.get_channel(int(category_id))
                if not isinstance(category, discord.CategoryChannel):
                    raise ProviderError("archive_category_unavailable", retry=False)
                args["category"] = category
        await channel.edit(**args)
        if (
            match["settings"]["threads"]["close_after"]
            or match["settings"]["archive"]["lock_threads"]
        ):
            for thread in channel.threads:
                await thread.edit(locked=True, archived=True, reason="Accepted closure policy")
        async with self.repo.unit() as unit:
            current = await unit.match(match["id"])
            current["archived"] = current["archived"] or bool(
                job["data"].get("move") and args.get("category")
            )
            await unit.save_match(current)

    async def permissions(self, job):
        match = await self.repo.match(job["match_id"])
        if not match["channel"]:
            return
        guild = self.guild(match["guild"])
        channel = await self.channel(match["channel"])
        config = await self.arena.config(match["guild"])
        members = []
        for player in match["players"]:
            try:
                members.append(
                    guild.get_member(int(player)) or await guild.fetch_member(int(player))
                )
            except discord.NotFound:
                pass
        await channel.edit(
            overwrites=overwrites(
                guild, match, config, members, guild.me, closed=match["state"] == "closed"
            ),
            sync_permissions=False,
            reason="Restore accepted debate permissions",
        )

    async def notice(self, job):
        match = await self.repo.match(job["match_id"])
        data = job["data"]
        guard = data.get("guard")
        if guard and guard.get("claim"):
            claim = await self.repo.claim(guard["claim"], match["guild"])
            latest = next((h for h in reversed(claim["history"]) if "verdict" in h), {})
            if claim["stale"] or latest.get("job") != guard["check"]:
                return  # Do not publish a delayed flag after its wording/evidence was superseded.
        if data.get("user"):
            user = self.client.get_user(int(data["user"])) or await self.client.fetch_user(
                int(data["user"])
            )
            channel = await user.create_dm()
        elif data.get("destination"):
            channel = await self.channel(data["destination"])
        elif match["channel"]:
            channel = await self.channel(match["channel"])
        else:
            # Challenge announcements fall back to their originating channel/thread.
            origin_id = match["origin"].rstrip("/").split("/")[-1]
            channel = await self.channel(origin_id if origin_id.isdecimal() else None)
        text = data["text"]
        pieces = [text[i : i + 1700] for i in range(0, len(text), 1700)] or [""]
        for index, piece in enumerate(pieces):
            marker = hashlib.sha256(f"{job['id']}:{index}".encode()).hexdigest()[:24]
            async with self.repo.unit() as unit:
                delivered = await unit.document("delivery", marker)
            if delivered:
                continue
            footer = f"\n[Arena delivery {marker}]"
            # Resolve an ambiguous successful send after a crash before the SQL acknowledgement.
            found = None
            async for message in channel.history(
                limit=None, after=datetime.fromtimestamp(match["created"], UTC)
            ):
                if message.author.id == self.client.user.id and footer in message.content:
                    found = message
                    break
            if found is None:
                found = await channel.send(
                    piece + footer, allowed_mentions=discord.AllowedMentions.none()
                )
            async with self.repo.unit() as unit:
                await unit.save("delivery", marker, str(found.id))

    async def reconcile(self):
        async with self.repo.unit() as unit:
            rows = await unit.rows("SELECT id FROM matches WHERE channel IS NOT NULL")
        for row in rows:
            match = await self.repo.match(row["id"])
            try:
                channel = await self.channel(match["channel"])
            except discord.NotFound:
                await self.arena.channel_missing(match["channel"])
                continue
            seen = {}
            async for message in channel.history(
                limit=None, oldest_first=True, after=datetime.fromtimestamp(match["created"], UTC)
            ):
                if str(message.author.id) not in match["players"] or message.author.bot:
                    continue
                seen[str(message.id)] = message
                await self.arena.message(
                    match["guild"],
                    match["channel"],
                    str(message.id),
                    str(message.author.id),
                    message.content,
                    message.jump_url,
                    message.created_at.timestamp(),
                    message.author.bot,
                )
            async with self.repo.unit() as unit:
                official = await unit.rows(
                    "SELECT id,content,deleted FROM messages WHERE match_id=?", (match["id"],)
                )
            for original in official:
                message = seen.get(original["id"])
                if message is None and not original["deleted"]:
                    await self.arena.edit_message(original["id"], deleted=True)
                elif message and (message.content != original["content"] or original["deleted"]):
                    await self.arena.edit_message(original["id"], message.content)

    async def enforce_message(self, message):
        """Enforce posting policy during the short window before overwrite reconciliation."""
        async with self.repo.unit() as unit:
            row = await unit.one(
                "SELECT data FROM matches WHERE channel=?", (str(message.channel.id),)
            )
        if row is None or (self.client.user and message.author.id == self.client.user.id):
            return True
        match = json.loads(row["data"])
        config = await self.arena.config(match["guild"])
        author = message.author
        staff = getattr(getattr(author, "guild_permissions", None), "administrator", False) or any(
            str(role.id) in config["moderator_roles"] for role in getattr(author, "roles", [])
        )
        allowed = staff or (str(author.id) in match["players"] and match["state"] == "active")
        if not allowed:
            await message.delete()
        return allowed

    async def restrict_reaction(self, payload):
        if payload.guild_id != self.client.config.guild_id:
            return
        async with self.repo.unit() as unit:
            row = await unit.one(
                "SELECT data FROM matches WHERE channel=?", (str(payload.channel_id),)
            )
        if not row:
            return
        match = json.loads(row["data"])
        settings = match["settings"]["reactions"]
        if not settings["enabled"] or (
            settings["allowed"] and str(payload.emoji) not in settings["allowed"]
        ):
            channel = await self.channel(str(payload.channel_id))
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, discord.Object(id=payload.user_id))

    async def manual_archive(self, actor, match_id):
        from argument_arena.arena import require_staff

        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            config = await unit.document("guild", actor.guild)
            require_staff(actor, config or {})
            if match["state"] != "closed":
                raise ArenaError("Only completed matches can be archived.")
            await unit.job(
                f"manual-archive:{match_id}:{self.arena.clock()}",
                "archive",
                match_id,
                {"move": True},
                self.arena.clock(),
            )
            return "Archival queued with explicit permission preservation."
