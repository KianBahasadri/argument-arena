"""Typed controls for every match feature, shared by drafts and negotiation."""

from copy import deepcopy

import discord

from argument_arena.arena import participant
from argument_arena.messages import ADMIN_REQUIRED, RULES_LOCKED
from argument_arena.settings import ENUMS, WEIGHTS, ArenaError, match_settings, ranked_settings
from argument_arena.ui import Field, Form, Panel, actor, number, respond, text

FEATURES = {
    "claims": "Claim ledger",
    "research": "Cited research",
    "on_demand": "Fact-check requests",
    "corrections": "Factual corrections",
    "fallacies": "Fallacy detection",
    "coaching": "Coaching",
    "civility": "Civility",
    "live_scores": "Live scores",
    "judging": "Final judging",
    "feedback": "Post-match feedback",
    "turns": "Turn order",
    "inactivity": "Response deadline",
    "reminders": "Deadline reminders",
    "limits": "Round and message limits",
    "reactions": "Audience reactions",
    "threads": "Discussion threads",
    "audience": "Audience vote",
    "ranked": "Ranked play",
    "profiles": "Profile insights",
    "archive": "Automatic archival",
}
DEPENDENCIES = (
    "Research off also turns factual corrections off. Judging off also turns ranked play off. "
    "Ranked-v1 requires its shared judging, coaching, live-score, turn, deadline and limit rules. "
    "Reminder lead time must be shorter than the response window. "
    "All AI features use the operator's single OpenCode Go model."
)


def parameters(values, prefix=()):
    for key, value in values.items():
        if key == "enabled":
            continue
        if isinstance(value, dict) and key != "weights":
            yield from parameters(value, (*prefix, key))
        else:
            yield (*prefix, key), value


class SettingsTarget:
    def __init__(self, client, owner, *, match_id=None, draft=None, server=False):
        self.client, self.owner = client, str(owner)
        self.match_id, self.draft, self.server = match_id, draft, server

    async def read(self):
        if self.draft is not None:
            self.draft.check()
            return self.draft.snapshot()
        if self.server:
            config = await self.client.arena.config(str(self.client.config.guild_id))
            return {"settings": config["defaults"], "revision": None}
        return await self.client.arena.repo.match(self.match_id, str(self.client.config.guild_id))

    async def update(self, interaction, patch, revision):
        who = actor(interaction)
        if who.id != self.owner or who.guild != str(self.client.config.guild_id):
            raise ArenaError(
                "This settings panel belongs to another member or server, so this edit cannot"
                " be applied. Open your own `/match` or challenge setup in the configured "
                "server, then choose Features to make an authorized change."
            )
        if self.draft is not None:
            async with self.draft.lock:
                self.draft.check(revision)
                self.draft.settings = match_settings(patch, self.draft.settings)
                self.draft.revision += 1
        elif self.server:
            await self.client.arena.setup(who, {"defaults": patch})
        else:
            await self.client.arena.settings(who, self.match_id, patch, expected_revision=revision)

    async def show(self, interaction):
        if self.draft is not None:
            from argument_arena.match_ui import show_draft

            await show_draft(interaction, self.draft)
        elif self.server:
            await show_settings(interaction, self)
        else:
            from argument_arena.match_ui import show_match

            await show_match(interaction, self.client, self.match_id)

    async def editable(self, interaction):
        current = await self.read()
        if not self.server and self.draft is None:
            participant(current, actor(interaction))
            if current["state"] != "challenge":
                raise ArenaError(RULES_LOCKED)
        if self.server and not actor(interaction).admin:
            raise ArenaError(ADMIN_REQUIRED)
        return current


class FeatureView(Panel):
    def __init__(self, target, current, feature, editable):
        super().__init__(target.client, target.owner)
        self.target, self.current, self.feature = target, current, feature
        self.editable = editable
        values = current["settings"][feature]
        if editable:
            self.button("Turn off" if values["enabled"] else "Turn on", self.toggle, row=0)
            fields = list(parameters(values))
            if fields:
                self.actions(
                    [
                        (".".join(path), " / ".join(path).replace("_", " ").title())
                        for path, value in fields
                    ],
                    self.parameter,
                    row=1,
                )
        self.button("Back to summary", target.show, row=3)
        self.button("Full feature details", self.details, row=3)

    async def details(self, interaction):
        current = await self.target.read()
        await respond(interaction, {self.feature: current["settings"][self.feature]})

    async def toggle(self, interaction):
        current = await self.target.editable(interaction)
        patch = {self.feature: {"enabled": not current["settings"][self.feature]["enabled"]}}
        if self.feature == "ranked" and not current["settings"]["ranked"]["enabled"]:
            ranked = ranked_settings()
            patch = {
                name: ranked[name]
                for name in (
                    "ranked",
                    "judging",
                    "coaching",
                    "live_scores",
                    "turns",
                    "inactivity",
                    "limits",
                )
            }
        await self.target.update(
            interaction,
            patch,
            current["revision"],
        )
        await self.target.show(interaction)

    async def parameter(self, interaction, name):
        current = await self.target.editable(interaction)
        fields = dict(
            (".".join(path), value) for path, value in parameters(current["settings"][self.feature])
        )
        if name not in fields:
            raise ArenaError(
                "This parameter is not available in the current feature settings. Reopen "
                "Features from the latest match, draft or admin panel and select a parameter "
                "from its menu. An older panel may refer to rules that have since changed."
            )
        value = fields[name]

        async def save(request, new):
            patch = deepcopy(current["settings"][self.feature])
            part = patch
            keys = name.split(".")
            for key in keys[:-1]:
                part = part[key]
            part[keys[-1]] = new
            await self.target.update(request, {self.feature: patch}, current["revision"])
            await self.target.show(request)

        choices = None
        if isinstance(value, bool):
            choices = [("On", True), ("Off", False)]
        elif (self.feature, name) in ENUMS:
            choices = [(v.replace("_", " ").title(), v) for v in sorted(ENUMS[self.feature, name])]
        elif name == "model":
            choices = [("Operator's OpenCode Go model", "default")]
        elif self.feature == "turns" and name == "first":
            choices = [("Challenger goes first", 0), ("Opponent goes first", 1)]
        if choices is not None:
            panel = Panel(self.client, self.owner)

            async def chosen(request, selected):
                await save(request, choices[int(selected)][1])

            panel.actions(
                [(str(i), label) for i, (label, item) in enumerate(choices)],
                chosen,
                styles={
                    str(i): discord.ButtonStyle.primary
                    for i, (_, item) in enumerate(choices)
                    if item == value
                },
            )
            await respond(interaction, f"**{FEATURES[self.feature]} → {text(name)}**", panel)
            return

        async def submitted(request, values):
            raw = values["value"]
            if isinstance(value, dict):
                parts = raw.split()
                if len(parts) != len(value):
                    raise ArenaError(
                        "Enter six whole-number weights separated by spaces, in this order: "
                        "reasoning, evidence, accuracy, engagement, clarity and rules. They "
                        "must total 100; for example, 25 20 15 20 10 10. Reopen the weights "
                        "form and replace all six values together."
                    )
                parsed = {key: number(item, key) for key, item in zip(WEIGHTS, parts, strict=True)}
            elif isinstance(value, list):
                parsed = [line.strip() for line in raw.splitlines() if line.strip()]
            elif type(value) in (int, float):
                parsed = number(raw, name, decimal=isinstance(value, float))
            else:
                parsed = raw
            await save(request, parsed)

        await interaction.response.send_modal(
            Form(
                self,
                "Edit match parameter",
                [
                    Field(
                        "value",
                        "Reason Evidence Accuracy Engage Clarity Rules"
                        if isinstance(value, dict)
                        else (
                            name.replace("_", " ")
                            + (" (one per line)" if isinstance(value, list) else "")
                        )[:45],
                        " ".join(str(value[key]) for key in WEIGHTS)
                        if isinstance(value, dict)
                        else "\n".join(value)
                        if isinstance(value, list)
                        else str(value),
                        required=not isinstance(value, list),
                        paragraph=isinstance(value, list),
                        max_length=4000,
                    )
                ],
                submitted,
            )
        )


async def show_settings(interaction, target):
    current = await target.read()
    editable = (
        target.draft is not None
        or (target.server and actor(interaction).admin)
        or (
            not target.server
            and actor(interaction).id in current.get("players", [])
            and current.get("state") == "challenge"
        )
    )
    panel = Panel(target.client, target.owner)

    async def selected(request, feature):
        fresh = await target.read()
        values = fresh["settings"][feature]
        embed = discord.Embed(title=FEATURES[feature], description=DEPENDENCIES)
        embed.add_field(name="Enabled", value="On" if values["enabled"] else "Off")
        lines = [
            f"**{' / '.join(path)}:** {text(value, 150)}" for path, value in parameters(values)
        ]
        if lines:
            embed.add_field(name="Parameters", value="\n".join(lines)[:1024], inline=False)
        await respond(request, embed, FeatureView(target, fresh, feature, editable))

    panel.select(
        "Review a feature and its parameters",
        [
            discord.SelectOption(
                label=f"{FEATURES[name]}: {'ON' if value['enabled'] else 'OFF'}", value=name
            )
            for name, value in current["settings"].items()
        ],
        selected,
    )
    if not target.server:
        panel.button("Back to summary", target.show, row=1)
    await respond(
        interaction, discord.Embed(title="Match features", description=DEPENDENCIES), panel
    )
