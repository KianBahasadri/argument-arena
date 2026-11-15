"""Execution-authorized administration, with pickers for ordinary server setup."""

import discord

from argument_arena.arena import require_staff
from argument_arena.match_ui import show_picker, show_staff
from argument_arena.messages import ADMIN_REQUIRED, ROUTES_HELP
from argument_arena.settings import ArenaError
from argument_arena.settings_ui import SettingsTarget, show_settings
from argument_arena.ui import Field, Form, Panel, actor, parse_json, respond, safe


async def administrator(interaction):
    if not actor(interaction).admin:
        raise ArenaError(ADMIN_REQUIRED)


async def show_admin(interaction, client):
    config = await client.arena.config(str(interaction.guild_id))
    require_staff(actor(interaction), config)
    panel = Panel(client, str(interaction.user.id))
    options = [("moderate", "Moderate a match")]
    if actor(interaction).admin:
        options += [
            ("routes", "Set up routes"),
            ("outputs", "Output channels and moderator roles"),
            ("defaults", "Default match features"),
            ("config", "View server configuration"),
            ("advanced", "Advanced server policy"),
            ("audit", "Server audit history"),
            ("diagnostic", "Connection diagnostic"),
        ]

    async def selected(request, name):
        fresh = await client.arena.config(str(request.guild_id))
        require_staff(actor(request), fresh)
        if name == "moderate":

            async def chosen(item, match_id):
                match = await client.arena.repo.match(match_id, str(item.guild_id))
                await show_staff(item, client, match)

            await show_picker(request, client, all_matches=True, selected=chosen)
            return
        await administrator(request)
        if name == "routes":
            await respond(
                request,
                ROUTES_HELP,
                RoutesView(client, str(request.user.id)),
            )
        elif name == "outputs":
            await respond(
                request,
                "Choose optional announcement/results channels and moderator roles,"
                " then save. Omitted fields keep their current values.",
                OutputsView(client, str(request.user.id)),
            )
        elif name == "defaults":
            await show_settings(request, SettingsTarget(client, str(request.user.id), server=True))
        elif name == "config":
            await respond(request, fresh)
        elif name == "audit":
            async with client.arena.repo.unit() as unit:
                events = await unit.rows(
                    "SELECT * FROM events WHERE match_id=? ORDER BY id",
                    (f"guild:{request.guild_id}",),
                )
            await respond(request, events)
        elif name == "diagnostic":
            await client.diagnostic(request)
        elif name == "advanced":

            async def submitted(item, values):
                await safe(item, client.arena.setup(actor(item), parse_json(values["patch"])))

            await request.response.send_modal(
                Form(
                    panel,
                    "Advanced server policy",
                    [
                        Field(
                            "patch",
                            "Documented server policy patch (JSON)",
                            "{}",
                            max_length=4000,
                            paragraph=True,
                        )
                    ],
                    submitted,
                )
            )
        else:
            raise ArenaError(
                "This administration action is not recognized by the running bot. Reopen "
                "`/admin` and choose an option from its current menu. If a fresh menu still "
                "fails, ask the bot operator to check the deployment and logs."
            )

    panel.select(
        "Choose an administration action",
        [discord.SelectOption(label=label, value=name) for name, label in options],
        selected,
    )
    await respond(
        interaction,
        "**Administration**\nServer setup requires Administrator. Configured "
        "moderators can manage matches. Actions are checked again when used and "
        "recorded in the audit history.",
        panel,
    )


class RoutesView(Panel):
    def __init__(self, client, owner):
        super().__init__(client, owner)
        self.routes = {}
        for row, key in enumerate(("active", "completed", "cancelled")):
            picker = discord.ui.ChannelSelect(
                placeholder=f"{key.title()} matches category",
                channel_types=[discord.ChannelType.category],
                row=row,
            )

            async def chosen(interaction, picker=picker, key=key):
                await administrator(interaction)
                channel = picker.values[0]
                if channel.guild.id != interaction.guild_id:
                    raise ArenaError(
                        "The selected category belongs to another Discord server. Choose an "
                        "existing category from this server in each setup dropdown, then "
                        "click Save routes. A category is a folder in this server's channel "
                        "list; one folder can be used for multiple match states."
                    )
                self.routes[key] = str(channel.id)
                await respond(
                    interaction,
                    f"{key.title()} category selected. Select all three, then Save routes.",
                )

            picker.callback = chosen
            self.add_item(picker)
        self.button("Save routes", self.save, style=discord.ButtonStyle.success, row=3)

    async def save(self, interaction):
        await administrator(interaction)
        if set(self.routes) != {"active", "completed", "cancelled"}:
            missing = ", ".join(
                key.title()
                for key in ("active", "completed", "cancelled")
                if key not in self.routes
            )
            raise ArenaError(
                f"Category setup is incomplete. Choose {missing} before clicking Save routes. "
                "You can use the same Discord category in multiple dropdowns. Completed "
                "also holds forfeited matches. Your existing saved routes have not changed."
            )
        await safe(
            interaction,
            self.client.arena.setup(actor(interaction), {"categories": dict(self.routes)}),
        )


class OutputsView(Panel):
    def __init__(self, client, owner):
        super().__init__(client, owner)
        self.patch = {}
        for row, key in enumerate(("announcement", "results")):
            picker = discord.ui.ChannelSelect(
                placeholder=f"Optional {key} channel (empty clears)",
                min_values=0,
                max_values=1,
                channel_types=[discord.ChannelType.text],
                row=row,
            )

            async def chosen(interaction, picker=picker, key=key):
                await administrator(interaction)
                if picker.values and picker.values[0].guild.id != interaction.guild_id:
                    raise ArenaError(
                        "Announcement and results channels must belong to this Discord "
                        "server. Select a text channel from this server in the dropdown, or "
                        "leave the optional selection empty to clear it, then click Save "
                        "outputs."
                    )
                self.patch[key] = str(picker.values[0].id) if picker.values else None
                await respond(
                    interaction,
                    f"{key.title()} selection saved in this form. Click Save outputs to apply.",
                )

            picker.callback = chosen
            self.add_item(picker)
        roles = discord.ui.RoleSelect(
            placeholder="Moderator roles (empty clears)", min_values=0, max_values=25, row=2
        )

        async def selected(interaction):
            await administrator(interaction)
            if any(role.guild.id != interaction.guild_id for role in roles.values):
                raise ArenaError(
                    "Moderator roles must belong to this Discord server. Choose this server's"
                    " roles from the dropdown, then click Save outputs. Members of those "
                    "roles will be able to manage matches; server configuration still "
                    "requires Administrator permission."
                )
            self.patch["moderator_roles"] = [str(role.id) for role in roles.values]
            await respond(
                interaction, "Moderator selection saved in this form. Click Save outputs to apply."
            )

        roles.callback = selected
        self.add_item(roles)
        self.button("Save outputs", self.save, style=discord.ButtonStyle.success, row=3)

    async def save(self, interaction):
        await administrator(interaction)
        await safe(interaction, self.client.arena.setup(actor(interaction), dict(self.patch)))
