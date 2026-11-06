"""Gateway client and the small application-command surface for this foundation."""

import logging
import math

import discord
from discord import app_commands

from argument_arena import __version__
from argument_arena.config import Config
from argument_arena.storage import Storage

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
        message = "The command failed. Ask the operator to check the bot logs."
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

    async def setup_hook(self) -> None:
        # Called once per login, never from on_ready (which repeats after reconnects).
        if self.config.sync_commands:
            await self.tree.sync(guild=self.guild)
            logger.info("guild_commands_synchronized")

    async def on_connect(self) -> None:
        logger.info("gateway_connected")

    async def on_disconnect(self) -> None:
        self.gateway_ready = False
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
