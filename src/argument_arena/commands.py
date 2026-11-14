"""Slash commands and settings components; all authorization also lives in services."""

import io
import json
from datetime import UTC, datetime

import discord
from discord import app_commands

from argument_arena.arena import require_staff
from argument_arena.competition import leaderboard
from argument_arena.curriculum import LIBRARY
from argument_arena.repository import encode
from argument_arena.settings import Actor, ArenaError


def actor(interaction):
    if interaction.guild_id is None:
        raise ArenaError("Use this command in the configured server.")
    return Actor(
        str(interaction.user.id),
        str(interaction.guild_id),
        tuple(str(r.id) for r in getattr(interaction.user, "roles", [])),
        interaction.permissions.administrator,
        interaction.user.bot,
    )


def parse_json(value, expected=dict):
    try:
        result = json.loads(value)
        if not isinstance(result, expected):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ArenaError("Supply valid JSON with the documented structure.") from None


async def respond(interaction, value, view=None):
    content = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    kwargs = {"ephemeral": True, "allowed_mentions": discord.AllowedMentions.none()}
    if view:
        kwargs["view"] = view
    if len(content) > 1800:
        kwargs["file"] = discord.File(io.BytesIO(content.encode()), filename="arena-details.json")
        content = (
            "Full settings, evidence or report attached. Review these details before confirming."
        )
    sender = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    await sender(content, **kwargs)


async def safe(interaction, operation, view=None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    try:
        value = await operation
    except ArenaError as error:
        value = str(error)
    await respond(interaction, value, view)


class ScopedView(discord.ui.View):
    def __init__(self, client):
        super().__init__(timeout=300)
        self.client = client

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.client.config.guild_id:
            await respond(interaction, "This component belongs to another server.")
            return False
        return True

    async def on_error(self, interaction, error, item):
        await respond(
            interaction,
            str(error)
            if isinstance(error, ArenaError)
            else "The operation failed; use the slash command to retry.",
        )


class Parameters(discord.ui.Modal, title="Feature parameters"):
    def __init__(self, client, match, feature):
        super().__init__()
        self.client, self.match_id, self.feature = client, match["id"], feature
        self.value = discord.ui.TextInput(
            label=f"{feature} JSON (includes enabled)",
            style=discord.TextStyle.paragraph,
            default=json.dumps(match["settings"][feature]),
            max_length=4000,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction):
        if interaction.guild_id != self.client.config.guild_id:
            await respond(interaction, "This component belongs to another server.")
            return
        try:
            patch = {self.feature: parse_json(str(self.value))}
        except ArenaError as error:
            await respond(interaction, str(error))
            return
        await safe(
            interaction, self.client.arena.settings(actor(interaction), self.match_id, patch)
        )


class FeatureView(ScopedView):
    def __init__(self, client, match, feature):
        super().__init__(client)
        self.match, self.feature = match, feature

    @discord.ui.button(label="Toggle on / off", style=discord.ButtonStyle.secondary)
    async def toggle(self, interaction, button):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        enabled = current["settings"][self.feature]["enabled"]
        await safe(
            interaction,
            self.client.arena.settings(
                actor(interaction), current["id"], {self.feature: {"enabled": not enabled}}
            ),
        )

    @discord.ui.button(label="Edit parameters", style=discord.ButtonStyle.primary)
    async def parameters(self, interaction, button):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        await interaction.response.send_modal(Parameters(self.client, current, self.feature))


class SettingsView(ScopedView):
    def __init__(self, client, match):
        super().__init__(client)
        self.match = match
        select = discord.ui.Select(
            placeholder="Review every feature and its parameters",
            options=[
                discord.SelectOption(
                    label=f"{name}: {'ON' if settings['enabled'] else 'OFF'}", value=name
                )
                for name, settings in match["settings"].items()
            ],
        )
        select.callback = self.selected
        self.select = select
        self.add_item(select)

    async def selected(self, interaction):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        name = self.select.values[0]
        await respond(
            interaction, {name: current["settings"][name]}, FeatureView(self.client, current, name)
        )

    @discord.ui.button(label="Confirm this exact revision", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        await safe(
            interaction,
            self.client.arena.accept(actor(interaction), self.match["id"], self.match["revision"]),
        )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction, button):
        await safe(
            interaction, self.client.arena.action(actor(interaction), self.match["id"], "decline")
        )


class MatchCommands(app_commands.Group):
    def __init__(self, client):
        super().__init__(
            name="match", description="Create, manage and review a debate", guild_only=True
        )
        self.client = client

    @app_commands.command(description="Propose a debate from this channel or discussion thread")
    async def challenge(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        topic: str,
        your_position: str,
        their_position: str,
        preset: str = "default",
    ):
        if member.bot:
            await respond(
                interaction,
                "Choose a human opponent. Use /train start mode:battle for bot practice.",
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            match = await self.client.arena.challenge(
                actor(interaction),
                str(member.id),
                topic,
                [your_position, their_position],
                f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}",
                preset,
            )
            await respond(interaction, match, SettingsView(self.client, match))
        except ArenaError as error:
            await respond(interaction, str(error))

    @app_commands.command(description="Confirm the identical settings revision you reviewed")
    async def accept(self, interaction: discord.Interaction, match_id: str, revision: int):
        await safe(interaction, self.client.arena.accept(actor(interaction), match_id, revision))

    @app_commands.command(description="Decline a pending challenge")
    async def decline(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "decline"))

    @app_commands.command(
        description="Review effective settings or propose JSON feature/position changes"
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        match_id: str,
        patch: str | None = None,
        positions: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            match = await self.client.arena.settings(
                actor(interaction),
                match_id,
                parse_json(patch) if patch else None,
                parse_json(positions, list) if positions else None,
            )
            await respond(interaction, match, SettingsView(self.client, match))
        except ArenaError as error:
            await respond(interaction, str(error))

    @app_commands.command(
        description="Show state, speaker, exact deadline, rules and pending/failed work"
    )
    async def status(self, interaction: discord.Interaction, match_id: str):
        async def operation():
            match = await self.client.arena.repo.match(match_id, str(interaction.guild_id))
            async with self.client.arena.repo.unit() as unit:
                jobs = await unit.rows(
                    "SELECT kind,state,error,due FROM jobs WHERE match_id=? AND state!='done'",
                    (match_id,),
                )
            match["jobs"] = jobs
            if match["deadline"]:
                match["deadline_utc"] = datetime.fromtimestamp(match["deadline"], UTC).isoformat()
            return match

        await safe(interaction, operation())

    @app_commands.command(description="Submit your completed turn in a submit-mode debate")
    async def submit(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.submit(actor(interaction), match_id))

    @app_commands.command(
        description="View the attributed claim graph and research correction history"
    )
    async def claims(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.assistance.claims(match_id, str(interaction.guild_id)))

    @app_commands.command(description="Request independent on-demand factual research")
    async def check(self, interaction: discord.Interaction, claim_id: str):
        await safe(interaction, self.client.assistance.check(actor(interaction), claim_id))

    @app_commands.command(
        description="Dispute a claim or result, optionally with evidence and a related claim"
    )
    async def dispute(
        self,
        interaction: discord.Interaction,
        match_id: str,
        target: str,
        reason: str,
        source: str | None = None,
        related_claim: str | None = None,
    ):
        await safe(
            interaction,
            self.client.assistance.dispute(
                actor(interaction), match_id, target, reason, source, related_claim
            ),
        )

    @app_commands.command(
        description="Propose a pause, or agree to your opponent's identical proposal"
    )
    async def pause(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "pause"))

    @app_commands.command(description="Propose or agree to resuming the saved response clock")
    async def resume(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "resume"))

    @app_commands.command(description="Propose or agree to a response extension (1–168 hours)")
    async def extend(self, interaction: discord.Interaction, match_id: str, hours: int):
        await safe(
            interaction,
            self.client.arena.action(actor(interaction), match_id, "extend", {"hours": hours}),
        )

    @app_commands.command(
        description="Explicitly request a response in flexible-order play; requires agreement"
    )
    async def request(
        self, interaction: discord.Interaction, match_id: str, speaker: discord.Member
    ):
        await safe(
            interaction,
            self.client.arena.action(
                actor(interaction), match_id, "request", {"speaker": str(speaker.id)}
            ),
        )

    @app_commands.command(description="Concede an active or paused debate")
    async def concede(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "concede"))

    @app_commands.command(description="Propose or agree to a draw")
    async def draw(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "draw"))

    @app_commands.command(description="Propose or agree to finish and start enabled final judging")
    async def finish(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "finish"))

    @app_commands.command(
        description="Propose an agreed cancellation; staff may cancel immediately"
    )
    async def cancel(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.action(actor(interaction), match_id, "cancel"))

    @app_commands.command(
        description="View the result, rubric, report, feedback and separate audience vote"
    )
    async def result(self, interaction: discord.Interaction, match_id: str):
        async def operation():
            data = await self.client.arena.result(match_id, str(interaction.guild_id))
            match = await self.client.arena.repo.match(match_id, str(interaction.guild_id))
            data = json.loads(encode(data))
            private = match["settings"]["feedback"]["delivery"] == "private"
            enabled = match["settings"]["feedback"]["enabled"]
            for details in [
                (data.get("report") or {}).get("participants", {}),
                data.get("feedback", {}),
            ]:
                for user, detail in details.items():
                    if not enabled or (private and user != str(interaction.user.id)):
                        for key in ("strengths", "needs", "practice", "training", "unanswered"):
                            detail.pop(key, None)
            return data

        await safe(interaction, operation())

    @app_commands.command(description="Queue manual archival of a completed match (staff only)")
    async def archive(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.gateway.manual_archive(actor(interaction), match_id))

    @app_commands.command(
        description="Amend an outcome with an explanation and replay affected ratings (staff)"
    )
    async def correct(
        self,
        interaction: discord.Interaction,
        match_id: str,
        outcome: str,
        reason: str,
        winner: discord.Member | None = None,
    ):
        await safe(
            interaction,
            self.client.arena.correct(
                actor(interaction), match_id, outcome, str(winner.id) if winner else None, reason
            ),
        )

    @app_commands.command(
        description="Review match events and moderator/rating corrections (staff only)"
    )
    async def audit(self, interaction: discord.Interaction, match_id: str):
        async def operation():
            await self.client.arena.repo.match(match_id, str(interaction.guild_id))
            require_staff(
                actor(interaction), await self.client.arena.config(str(interaction.guild_id))
            )
            async with self.client.arena.repo.unit() as unit:
                return await unit.rows(
                    "SELECT * FROM events WHERE match_id=? ORDER BY id", (match_id,)
                )

        await safe(interaction, operation())

    @app_commands.command(
        description="Retry failed provider or Discord jobs after fixing configuration (staff)"
    )
    async def retry(self, interaction: discord.Interaction, match_id: str):
        await safe(interaction, self.client.arena.retry(actor(interaction), match_id))

    @app_commands.command(
        description="Close with an explicit staff decision when automatic judging is unresolved"
    )
    async def close(
        self,
        interaction: discord.Interaction,
        match_id: str,
        outcome: str,
        reason: str,
        winner: discord.Member | None = None,
    ):
        await safe(
            interaction,
            self.client.arena.close_match(
                actor(interaction), match_id, outcome, str(winner.id) if winner else None, reason
            ),
        )

    @app_commands.command(
        description="View managed match history and procedural results, including casual play"
    )
    async def history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        topic: str = "",
        days: int = 0,
    ):
        async def operation():
            if days < 0:
                raise ArenaError("Days must be nonnegative.")
            return await self.client.arena.history(
                str(interaction.guild_id),
                str((member or interaction.user).id),
                topic,
                self.client.arena.clock() - days * 86400 if days else 0,
            )

        await safe(interaction, operation())

    @app_commands.command(description="Cast a separate audience opinion after the match")
    async def vote(self, interaction: discord.Interaction, match_id: str, winner: discord.Member):
        await safe(
            interaction, self.client.arena.vote(actor(interaction), match_id, str(winner.id))
        )


class ProfileCommands(app_commands.Group):
    def __init__(self, client):
        super().__init__(
            name="profile", description="Consent-controlled argument profile", guild_only=True
        )
        self.client = client

    @app_commands.command(
        description="View a permitted profile with evidence, history and sample sizes"
    )
    async def view(self, interaction: discord.Interaction, member: discord.Member | None = None):
        await safe(
            interaction,
            self.client.profiles.view(actor(interaction), str((member or interaction.user).id)),
        )

    @app_commands.command(
        description="Set analysis, visibility, training inclusion and recommendations"
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        analysis: bool | None = None,
        visibility: str | None = None,
        training: bool | None = None,
        recommendations: bool | None = None,
    ):
        patch = {
            k: v
            for k, v in locals().items()
            if k in {"analysis", "visibility", "training", "recommendations"} and v is not None
        }
        await safe(interaction, self.client.profiles.settings(actor(interaction), patch))

    @app_commands.command(
        name="remove-insights", description="Remove generated insights and disable future analysis"
    )
    async def remove_insights(self, interaction: discord.Interaction):
        await safe(interaction, self.client.profiles.remove(actor(interaction)))

    @app_commands.command(
        description="Attach your correction or exclude a mischaracterized observation"
    )
    async def correct(
        self, interaction: discord.Interaction, match_id: str, note: str, exclude: bool = False
    ):
        await safe(
            interaction, self.client.profiles.correct(actor(interaction), match_id, note, exclude)
        )


class TrainCommands(app_commands.Group):
    def __init__(self, client):
        super().__init__(
            name="train", description="Original reasoning drills and bot battles", guild_only=True
        )
        self.client = client

    @app_commands.command(
        description="Start spot, selected, mixed, battle, repair or sound practice"
    )
    async def start(
        self,
        interaction: discord.Interaction,
        mode: str = "mixed",
        difficulty: int = 1,
        topic: str = "community projects",
        fallacy: str | None = None,
    ):
        await safe(
            interaction,
            self.client.training.start(actor(interaction), mode, fallacy, difficulty, topic),
        )

    @app_commands.command(description="Practice a chosen fallacy with an original exercise")
    async def fallacy(
        self,
        interaction: discord.Interaction,
        name: str,
        difficulty: int = 1,
        topic: str = "community projects",
    ):
        await safe(
            interaction,
            self.client.training.start(actor(interaction), "selected", name, difficulty, topic),
        )

    @app_commands.command(description="Request a hint for your current exercise")
    async def hint(self, interaction: discord.Interaction):
        await safe(interaction, self.client.training.hint(actor(interaction)))

    @app_commands.command(
        description="Explain your answer or repair; labels alone earn limited credit"
    )
    async def answer(self, interaction: discord.Interaction, explanation: str):
        await safe(interaction, self.client.training.answer(actor(interaction), explanation))

    @app_commands.command(description="View your current prompt, grading state and last feedback")
    async def current(self, interaction: discord.Interaction):
        async def operation():
            progress = await self.client.training.progress(actor(interaction))
            async with self.client.arena.repo.unit() as unit:
                jobs = await unit.rows(
                    "SELECT data,state,error FROM jobs WHERE kind='train_grade' AND state!='done'"
                )
            latest = progress["latest"]
            if latest:
                latest["jobs"] = [
                    {"state": row["state"], "status": row["error"]}
                    for row in jobs
                    if json.loads(row["data"])["session"] == latest["id"]
                ]
            return latest or "No training sessions yet."

        await safe(interaction, operation())

    @app_commands.command(
        description="View accuracy, recent changes, practice needs and recommendations"
    )
    async def progress(self, interaction: discord.Interaction):
        await safe(interaction, self.client.training.progress(actor(interaction)))

    @app_commands.command(
        description="List supported fallacy names and per-entry attribution links"
    )
    async def library(self, interaction: discord.Interaction):
        await respond(
            interaction,
            [
                {
                    "name": e.name,
                    "reference": e.reference,
                    "credit": "Bo Bennett, Logically Fallacious",
                }
                for e in LIBRARY
            ],
        )

    @app_commands.command(description="End your current training session")
    async def stop(self, interaction: discord.Interaction):
        await safe(interaction, self.client.training.stop(actor(interaction)))

    @app_commands.command(description="Retry unavailable training grading after provider setup")
    async def retry(self, interaction: discord.Interaction):
        await safe(interaction, self.client.training.retry(actor(interaction)))


class ServerCommands(app_commands.Group):
    def __init__(self, client):
        super().__init__(
            name="settings", description="Server policies and defaults", guild_only=True
        )
        self.client = client

    @app_commands.command(
        description="View configuration; administrators may apply a documented JSON patch"
    )
    async def server(self, interaction: discord.Interaction, patch: str | None = None):
        async def operation():
            if patch:
                return await self.client.arena.setup(actor(interaction), parse_json(patch))
            return await self.client.arena.config(str(interaction.guild_id))

        await safe(interaction, operation())

    @app_commands.command(
        description="View setup and server configuration audit history (administrator)"
    )
    async def audit(self, interaction: discord.Interaction):
        async def operation():
            if not interaction.permissions.administrator:
                raise ArenaError("Administrator permission required.")
            async with self.client.arena.repo.unit() as unit:
                return await unit.rows(
                    "SELECT * FROM events WHERE match_id=? ORDER BY id",
                    (f"guild:{interaction.guild_id}",),
                )

        await safe(interaction, operation())


def register(client):
    for group in (
        MatchCommands(client),
        ProfileCommands(client),
        TrainCommands(client),
        ServerCommands(client),
    ):
        client.tree.add_command(group, guild=client.guild)

    @app_commands.command(
        name="setup", description="Configure match categories, output channels and moderator role"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def setup(
        interaction: discord.Interaction,
        active: discord.CategoryChannel,
        completed: discord.CategoryChannel,
        forfeited: discord.CategoryChannel,
        cancelled: discord.CategoryChannel,
        announcement: discord.TextChannel | None = None,
        results: discord.TextChannel | None = None,
        moderator: discord.Role | None = None,
    ):
        async def operation():
            channels = [active, completed, forfeited, cancelled, announcement, results]
            if any(c and c.guild.id != interaction.guild_id for c in channels):
                raise ArenaError("All routes must belong to this server.")
            return await client.arena.setup(
                actor(interaction),
                {
                    "categories": {
                        "active": str(active.id),
                        "completed": str(completed.id),
                        "forfeited": str(forfeited.id),
                        "cancelled": str(cancelled.id),
                    },
                    "announcement": str(announcement.id) if announcement else None,
                    "results": str(results.id) if results else None,
                    "moderator_roles": [str(moderator.id)] if moderator else [],
                },
            )

        await safe(interaction, operation())

    @app_commands.command(
        name="leaderboard",
        description="Competitive Elo and results, optionally filtered by topic, period or format",
    )
    @app_commands.guild_only()
    async def standings(
        interaction: discord.Interaction,
        topic: str = "",
        days: int = 0,
        format_name: str = "",
        minimum_matches: int = 1,
    ):
        async def operation():
            if days < 0 or minimum_matches < 1:
                raise ArenaError("Days must be nonnegative; minimum_matches must be at least one.")
            return await leaderboard(
                client.arena.repo,
                str(interaction.guild_id),
                topic,
                client.arena.clock() - days * 86400 if days else 0,
                format_name,
                minimum_matches,
            )

        await safe(interaction, operation())

    client.tree.add_command(setup, guild=client.guild)
    client.tree.add_command(standings, guild=client.guild)
