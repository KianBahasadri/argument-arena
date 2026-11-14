"""Guild-restricted Gateway and product service composition."""

import logging
import math

import discord
from discord import app_commands

from argument_arena import __version__
from argument_arena.arena import Arena
from argument_arena.assistance import Assistance
from argument_arena.commands import register
from argument_arena.config import Config
from argument_arena.discord_gateway import DiscordGateway
from argument_arena.profiles import Profiles
from argument_arena.providers import configured_providers
from argument_arena.settings import ArenaError
from argument_arena.storage import Storage
from argument_arena.training import Training
from argument_arena.worker import Worker

logger = logging.getLogger(__name__)


class ArenaCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.client.config.guild_id:
            await interaction.response.send_message(
                "This application is configured for another server.", ephemeral=True
            )
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        # Never include interaction tokens, user messages, arguments, or error messages in logs.
        logger.error("command_failed", exc_info=(type(error), error, error.__traceback__))
        original = getattr(error, "original", error)
        message = (
            str(original)
            if isinstance(original, ArenaError)
            else ("The command failed. Ask the operator to check the bot logs.")
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.warning("command_error_response_failed")


class ArenaClient(discord.Client):
    def __init__(self, config: Config, storage: Storage) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        intents.guild_reactions = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.storage = storage
        self.gateway_ready = False
        self.tree = ArenaCommandTree(self)
        self.guild = discord.Object(id=config.guild_id)
        command = app_commands.Command(
            name="diagnostic",
            description="Check the Argument Arena connection and storage",
            callback=self.diagnostic,
        )
        command.guild_only = True
        command.default_permissions = discord.Permissions(administrator=True)
        self.tree.add_command(command, guild=self.guild)
        self.arena = Arena(storage)
        llm, research = configured_providers(config)
        self.assistance = Assistance(self.arena, llm, research)
        self.training = Training(self.arena, llm)
        self.profiles = Profiles(self.arena)
        self.gateway = DiscordGateway(self, self.arena)
        self.worker = Worker(
            self, self.arena, self.assistance, self.training, self.profiles, self.gateway
        )
        register(self)

    async def setup_hook(self) -> None:
        # Called once per login, never from on_ready (which repeats after reconnects).
        if self.config.sync_commands:
            await self.tree.sync(guild=self.guild)
            logger.info("guild_commands_synchronized")

    async def on_connect(self) -> None:
        logger.info("gateway_connected")

    async def on_disconnect(self) -> None:
        self.gateway_ready = False
        self.worker.reconcile_needed = True
        logger.warning("gateway_disconnected")

    async def on_ready(self) -> None:
        self.gateway_ready = self.get_guild(self.config.guild_id) is not None
        if self.gateway_ready:
            logger.info("gateway_ready")
        else:
            logger.error("configured_guild_unavailable")

    async def on_resumed(self) -> None:
        self.gateway_ready = self.get_guild(self.config.guild_id) is not None
        logger.info("gateway_resumed")

    async def on_message(self, message: discord.Message) -> None:
        if message.guild and message.guild.id == self.config.guild_id:
            if not await self.gateway.enforce_message(message):
                return
            await self.arena.message(
                str(message.guild.id),
                str(message.channel.id),
                str(message.id),
                str(message.author.id),
                message.content,
                message.jump_url,
                message.created_at.timestamp(),
                message.author.bot,
            )

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if payload.guild_id == self.config.guild_id and "content" in payload.data:
            await self.arena.edit_message(str(payload.message_id), payload.data["content"])

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id == self.config.guild_id:
            await self.arena.edit_message(str(payload.message_id), deleted=True)

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if payload.guild_id == self.config.guild_id:
            for message_id in payload.message_ids:
                await self.arena.edit_message(str(message_id), deleted=True)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if channel.guild.id == self.config.guild_id:
            await self.arena.channel_missing(str(channel.id))

    async def on_guild_role_create(self, role: discord.Role) -> None:
        if role.guild.id == self.config.guild_id:
            async with self.arena.repo.unit() as unit:
                for row in await unit.rows(
                    "SELECT id FROM matches WHERE guild=? AND channel IS NOT NULL",
                    (str(role.guild.id),),
                ):
                    await unit.job(
                        f"new-role:{role.id}:{row['id']}",
                        "permissions",
                        row["id"],
                        {},
                        self.arena.clock(),
                    )

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self.gateway.restrict_reaction(payload)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        # Discord's default prints a traceback; arguments can include message content/secrets.
        logger.error("gateway_event_failed", exc_info=True)

    async def diagnostic(self, interaction: discord.Interaction) -> None:
        # Enforce permissions at execution too; administrators may edit Discord command defaults.
        if not interaction.permissions.administrator:
            await interaction.response.send_message(
                "Administrator permission required.", ephemeral=True
            )
            return
        await self.storage.check()
        latency = f"{self.latency * 1000:.0f} ms" if math.isfinite(self.latency) else "pending"
        await interaction.response.send_message(
            f"Argument Arena {__version__}: storage OK; Gateway latency {latency}.",
            ephemeral=True,
        )

    async def close(self) -> None:
        self.gateway_ready = False
        await super().close()
