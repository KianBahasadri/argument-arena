"""Seven guild-only entry points; detailed actions live in private menus and forms."""

import discord
from discord import app_commands

from argument_arena.admin_ui import show_admin
from argument_arena.help_ui import show_help
from argument_arena.match_ui import open_matches, start_challenge
from argument_arena.member_ui import show_leaderboard, show_profile, show_training
from argument_arena.settings import ArenaError
from argument_arena.ui import respond


def register(client):
    @app_commands.command(
        name="challenge", description="Choose an opponent, then set up a debate together"
    )
    @app_commands.guild_only()
    @app_commands.describe(member="The human server member you want to challenge")
    async def challenge(interaction: discord.Interaction, member: discord.Member):
        try:
            await start_challenge(interaction, client, member)
        except ArenaError as error:
            await respond(interaction, str(error))

    @app_commands.command(
        name="match",
        description="Choose a debate and open its status, settings, controls or results",
    )
    @app_commands.guild_only()
    async def matches(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_matches(interaction, client)

    @app_commands.command(
        name="train", description="Private reasoning exercises, bot battles, hints and progress"
    )
    @app_commands.guild_only()
    async def train(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await show_training(interaction, client)

    @app_commands.command(
        name="profile",
        description="Profiles, public match history, privacy preferences and corrections",
    )
    @app_commands.guild_only()
    async def profile(interaction: discord.Interaction):
        await show_profile(interaction, client)

    @app_commands.command(
        name="leaderboard",
        description="Competitive standings with topic, time, format and activity filters",
    )
    @app_commands.guild_only()
    async def standings(interaction: discord.Interaction):
        await show_leaderboard(interaction, client)

    @app_commands.command(
        name="admin", description="Authorized server setup, diagnostics and match moderation"
    )
    @app_commands.guild_only()
    async def admin(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await show_admin(interaction, client)

    @app_commands.command(
        name="help", description="Match quick start, ending options and guidance for every feature"
    )
    @app_commands.guild_only()
    async def help_command(interaction: discord.Interaction):
        await show_help(interaction, client)

    for command in (challenge, matches, train, profile, standings, admin, help_command):
        client.tree.add_command(command, guild=client.guild)
