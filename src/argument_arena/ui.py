"""Shared, private Discord panels and forms; services remain the authority boundary."""

import asyncio
import io
import json
from dataclasses import dataclass

import discord

from argument_arena.settings import Actor, ArenaError


def actor(interaction):
    if interaction.guild_id is None:
        raise ArenaError("Use this command in the configured server.")
    return Actor(
        str(interaction.user.id),
        str(interaction.guild_id),
        tuple(str(role.id) for role in getattr(interaction.user, "roles", [])),
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


def number(value, label, *, decimal=False):
    try:
        return float(value) if decimal else int(value)
    except ValueError:
        raise ArenaError(f"{label} must be a number.") from None


def text(value, limit=1000):
    return discord.utils.escape_markdown(str(value))[:limit]


async def respond(interaction, value, view=None):
    kwargs = {"ephemeral": True, "allowed_mentions": discord.AllowedMentions.none()}
    content = None
    if isinstance(value, discord.Embed):
        kwargs["embed"] = value
    else:
        content = (
            value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
        )
        if len(content) > 1800:
            kwargs["file"] = discord.File(
                io.BytesIO(content.encode()), filename="arena-details.json"
            )
            content = "Full details attached. These are visible only to you."
    if view is not None:
        kwargs["view"] = view
    sender = (
        interaction.followup.send
        if interaction.response.is_done()
        else interaction.response.send_message
    )
    await sender(content, **kwargs)


async def safe(interaction, operation, view=None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        value = await operation
    except ArenaError as error:
        value = str(error)
    await respond(interaction, value, view)


class Panel(discord.ui.View):
    def __init__(self, client, owner, *, timeout=900):
        super().__init__(timeout=timeout)
        self.client, self.owner = client, str(owner)

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.client.config.guild_id:
            await respond(interaction, "This panel belongs to another server.")
            return False
        if str(interaction.user.id) != self.owner:
            await respond(interaction, "Open your own panel using the slash command.")
            return False
        if self.is_finished():
            await respond(interaction, "This panel expired. Open the slash command again.")
            return False
        return True

    async def on_error(self, interaction, error, item):
        await respond(
            interaction,
            str(error)
            if isinstance(error, ArenaError)
            else "The operation failed. Reopen the menu to retry.",
        )

    def button(self, label, callback, *, style=discord.ButtonStyle.secondary, row=None):
        item = discord.ui.Button(label=label, style=style, row=row)

        async def selected(interaction):
            await callback(interaction)

        item.callback = selected
        self.add_item(item)
        return item

    def select(self, placeholder, options, callback, *, row=None):
        item = discord.ui.Select(placeholder=placeholder, options=options, row=row)

        async def selected(interaction):
            await callback(interaction, item.values[0])

        item.callback = selected
        self.add_item(item)
        return item


@dataclass
class Field:
    key: str
    label: str
    default: str = ""
    required: bool = True
    max_length: int = 500
    min_length: int | None = None
    paragraph: bool = False


class Form(discord.ui.Modal):
    def __init__(self, parent, title, fields, submit):
        super().__init__(title=title, timeout=900)
        self.parent, self.submit = parent, submit
        self.inputs = {}
        for field in fields:
            item = discord.ui.TextInput(
                label=field.label,
                default=field.default or None,
                required=field.required,
                max_length=field.max_length,
                min_length=field.min_length,
                style=discord.TextStyle.paragraph if field.paragraph else discord.TextStyle.short,
            )
            self.inputs[field.key] = item
            self.add_item(item)

    async def on_submit(self, interaction):
        if not await self.parent.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.submit(
                interaction, {key: str(item).strip() for key, item in self.inputs.items()}
            )
        except ArenaError as error:
            await respond(interaction, str(error))

    async def on_error(self, interaction, error):
        await self.parent.on_error(interaction, error, None)


class Confirm(Panel):
    def __init__(self, client, owner, operation):
        super().__init__(client, owner)
        self.operation, self.lock = operation, asyncio.Lock()
        self.button("Confirm", self.confirm, style=discord.ButtonStyle.danger)
        self.button("Go back without changing anything", self.cancel)

    async def confirm(self, interaction):
        async with self.lock:
            if self.is_finished():
                await respond(interaction, "This confirmation has already been used or expired.")
                return
            self.stop()
            await self.operation(interaction)

    async def cancel(self, interaction):
        self.stop()
        await respond(interaction, "No change made. Reopen the menu to continue.")
