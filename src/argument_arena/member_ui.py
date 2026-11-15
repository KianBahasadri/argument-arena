"""Training, consent-controlled profiles and standings without routine IDs or JSON."""

import json

import discord

from argument_arena.competition import leaderboard
from argument_arena.curriculum import LIBRARY
from argument_arena.match_ui import show_picker
from argument_arena.messages import job_guidance
from argument_arena.settings import ArenaError
from argument_arena.ui import Confirm, Field, Form, Panel, actor, number, respond, safe, text


async def training_current(client, who):
    progress = await client.training.progress(who)
    latest = progress["latest"]
    if latest:
        async with client.arena.repo.unit() as unit:
            jobs = await unit.rows(
                "SELECT data,state,error FROM jobs WHERE kind='train_grade' AND state!='done'"
            )
        latest["jobs"] = [
            {
                "state": row["state"],
                "status": row["error"],
                "explanation": job_guidance(row["error"], row["state"], training=True),
            }
            for row in jobs
            if json.loads(row["data"])["session"] == latest["id"]
        ]
    return latest


class TrainingView(Panel):
    def __init__(self, client, owner, latest):
        super().__init__(client, owner)
        active = latest and latest["state"] in {"active", "grading"}
        if active and latest["state"] == "active":
            options = [("answer", "Answer exercise"), ("hint", "Request a hint")]
        elif active:
            options = [("retry", "Retry failed grading")]
        else:
            options = [("start", "Start practice")]
        options += [
            ("current", "Current exercise"),
            ("progress", "Progress"),
            ("library", "Fallacy library"),
        ]
        if active:
            options.append(("stop", "Stop session"))
        self.options = {key for key, label in options}
        self.actions(
            options,
            self.selected,
            columns=2,
            styles={
                "start": discord.ButtonStyle.primary,
                "answer": discord.ButtonStyle.primary,
                "retry": discord.ButtonStyle.primary,
                "stop": discord.ButtonStyle.danger,
            },
        )

    async def selected(self, interaction, action):
        if action not in self.options:
            raise ArenaError(
                "This training action is not available in the panel you opened. Your exercise"
                " or grading state may have changed. Reopen `/train` to see Current exercise "
                "and choose an action from the latest menu."
            )
        if action == "start":
            panel = Panel(self.client, self.owner)

            async def mode(request, selected):
                if selected == "selected":
                    await training_library(request, self.client, practice=True)
                else:
                    await training_difficulty(request, self.client, selected)

            panel.actions(
                [
                    ("spot", "Spot a fallacy"),
                    ("selected", "Choose a fallacy"),
                    ("mixed", "Mixed practice"),
                    ("battle", "Three-turn bot battle"),
                    ("repair", "Repair an argument"),
                    ("sound", "Sound or fallacious?"),
                ],
                mode,
                columns=2,
            )
            await respond(
                interaction, "Practice is private and never changes competitive ratings.", panel
            )
        elif action == "answer":

            async def answer(request, values):
                await safe(request, self.client.training.answer(actor(request), values["answer"]))

            await interaction.response.send_modal(
                Form(
                    self,
                    "Explain your answer",
                    [
                        Field(
                            "answer",
                            "Reasoning, quotation or repair",
                            min_length=10,
                            max_length=4000,
                            paragraph=True,
                        )
                    ],
                    answer,
                )
            )
        elif action == "library":
            await training_library(interaction, self.client)
        elif action == "current":
            await show_training(interaction, self.client)
        elif action == "stop":

            async def stop(request):
                await self.client.training.stop(actor(request))
                await show_training(request, self.client)

            await respond(
                interaction,
                "Stop your current session? Completed practice is retained.",
                Confirm(self.client, self.owner, stop),
            )
        else:
            method = {
                "hint": self.client.training.hint,
                "progress": self.client.training.progress,
                "retry": self.client.training.retry,
            }[action]
            await safe(interaction, method(actor(interaction)))


async def show_training(interaction, client):
    latest = await training_current(client, actor(interaction))
    if latest:
        embed = discord.Embed(
            title=f"Training · {latest['state']}", description=text(latest["prompt"], 2000)
        )
        embed.add_field(name="Your task", value=text(latest["instruction"], 1000), inline=False)
        if latest.get("last_feedback"):
            feedback = latest["last_feedback"]
            embed.add_field(
                name="Last feedback",
                value=text(feedback.get("feedback", feedback), 1000),
                inline=False,
            )
        if latest.get("generation"):
            embed.add_field(
                name="Generation status", value=text(latest["generation"], 500), inline=False
            )
        if latest.get("jobs"):
            embed.add_field(
                name="Grading status",
                value="\n\n".join(job["explanation"] for job in latest["jobs"])[:1024],
                inline=False,
            )
        embed.set_footer(
            text=f"{latest['mode']} · difficulty {latest['difficulty']} · turn {latest['turn']}"
        )
    else:
        embed = discord.Embed(
            title="Reasoning practice",
            description="Start an original exercise or bot battle. Answers, hints and progress "
            "are private. No session IDs are needed.",
        )
    await respond(interaction, embed, TrainingView(client, str(interaction.user.id), latest))


async def training_library(interaction, client, *, practice=False, mode="selected"):
    panel = Panel(client, str(interaction.user.id))

    async def selected(request, name):
        entry = next(entry for entry in LIBRARY if entry.name == name)
        if practice:
            await training_difficulty(request, client, mode, entry.name)
        else:
            details = Panel(client, str(request.user.id))

            async def start(item):
                await training_difficulty(item, client, "selected", entry.name)

            details.button("Practice this fallacy", start)
            await respond(
                request,
                f"**{text(entry.name)}**\nFurther reading: Bo Bennett, Logically Fallacious\n"
                f"{entry.reference}",
                details,
            )

    panel.select(
        "Choose a fallacy",
        [discord.SelectOption(label=entry.name, value=entry.name) for entry in LIBRARY],
        selected,
    )
    await respond(
        interaction,
        "Choose a reasoning error. Exercises are original; reference links credit "
        "Bo Bennett's Logically Fallacious.",
        panel,
    )


async def training_difficulty(interaction, client, mode, fallacy=None):
    panel = Panel(client, str(interaction.user.id))

    async def selected(request, difficulty):
        async def start(item, values):
            await client.training.start(
                actor(item), mode, fallacy, int(difficulty), values["topic"]
            )
            await show_training(item, client)

        await request.response.send_modal(
            Form(
                panel,
                "Choose a practice topic",
                [Field("topic", "Topic", "community projects", max_length=100)],
                start,
            )
        )

    panel.actions(
        [
            (str(value), label)
            for value, label in [
                (1, "1 · introductory"),
                (2, "2 · intermediate"),
                (3, "3 · challenging"),
            ]
        ],
        selected,
    )
    if fallacy is None:

        async def pick_fallacy(request):
            await training_library(request, client, practice=True, mode=mode)

        panel.button("Choose a fallacy (optional)", pick_fallacy, row=1)
    await respond(
        interaction,
        f"**{mode.title()}**"
        + (f" · {text(fallacy)}" if fallacy else "")
        + "\nChoose difficulty, then enter a topic.",
        panel,
    )


class ProfileView(Panel):
    def __init__(self, client, owner, user):
        super().__init__(client, owner)
        self.user = str(user)
        choices = [("view", "View profile"), ("history", "Public match history")]
        if self.user == self.owner:
            choices += [
                ("preferences", "Privacy and consent"),
                ("correct", "Correct or exclude an insight"),
                ("remove", "Remove generated insights"),
            ]
        self.choices = {key for key, label in choices}
        self.actions(
            choices,
            self.selected,
            columns=2,
            styles={"remove": discord.ButtonStyle.danger},
        )
        picker = discord.ui.UserSelect(placeholder="Choose another server member", row=3)

        async def selected(interaction):
            member = picker.values[0]
            await show_profile(interaction, client, str(member.id))

        picker.callback = selected
        self.add_item(picker)

    async def selected(self, interaction, action):
        if action not in self.choices:
            raise ArenaError(
                "Privacy, corrections and insight removal can only be managed for your own "
                "profile. Run `/profile` yourself and select your own profile to open those "
                "controls. Viewing another member's panel does not grant access to their "
                "private information or preferences."
            )
        if action == "view":
            await safe(interaction, self.client.profiles.view(actor(interaction), self.user))
        elif action == "history":
            await show_history(interaction, self.client, self.user)
        elif action == "preferences":
            await profile_preferences(interaction, self.client)
        elif action == "remove":

            async def remove(request):
                await safe(request, self.client.profiles.remove(actor(request)))

            await respond(
                interaction,
                "Delete generated insights and disable future analysis? Match "
                "records and completed training remain separate records.",
                Confirm(self.client, self.owner, remove),
            )
        else:

            async def chosen(request, match_id):
                controls = Panel(self.client, self.owner)

                async def edit(item, exclude):
                    async def submitted(req, values):
                        await safe(
                            req,
                            self.client.profiles.correct(
                                actor(req), match_id, values["note"], exclude == "exclude"
                            ),
                        )

                    await item.response.send_modal(
                        Form(
                            controls,
                            "Correct your generated insight",
                            [
                                Field(
                                    "note",
                                    "Your correction",
                                    min_length=5,
                                    max_length=2000,
                                    paragraph=True,
                                )
                            ],
                            submitted,
                        )
                    )

                controls.actions(
                    [
                        ("include", "Keep with correction"),
                        ("exclude", "Exclude with correction"),
                    ],
                    edit,
                    columns=2,
                )
                await respond(request, "Only your own observation is changed.", controls)

            await show_picker(interaction, self.client, selected=chosen)


async def show_profile(interaction, client, user=None):
    user = user or str(interaction.user.id)
    # Opening public history must not read or reveal generated insights.
    await respond(
        interaction,
        discord.Embed(
            title="Argument profile",
            description=f"Member {user}\n"
            "Generated insights respect consent and visibility at every "
            "read. Public match records are separate. Choose View profile to read permitted "
            "insights.",
        ),
        ProfileView(client, str(interaction.user.id), user),
    )


async def profile_preferences(interaction, client):
    prefs = await client.profiles.settings(actor(interaction))
    panel = Panel(client, str(interaction.user.id))

    async def selected(request, key):
        # Re-read at execution so a second panel cannot toggle a stale value.
        fresh = await client.profiles.settings(actor(request))
        value = (
            ("public" if fresh[key] == "private" else "private")
            if key == "visibility"
            else not fresh[key]
        )
        await client.profiles.settings(actor(request), {key: value})
        await profile_preferences(request, client)

    names = {
        "analysis": "Generate insights for future matches",
        "visibility": "Profile visibility",
        "training": "Include training progress",
        "recommendations": "Practice recommendations",
    }
    panel.actions(
        [
            ("analysis", "Disable insights" if prefs["analysis"] else "Enable insights"),
            (
                "visibility",
                "Make profile public"
                if prefs["visibility"] == "private"
                else "Make profile private",
            ),
            (
                "training",
                "Hide training progress" if prefs["training"] else "Include training progress",
            ),
            (
                "recommendations",
                "Disable recommendations" if prefs["recommendations"] else "Enable recommendations",
            ),
        ],
        selected,
        columns=2,
    )
    await respond(
        interaction,
        "**Privacy and consent**\n"
        + "\n".join(f"{label}: **{prefs[key]}**" for key, label in names.items())
        + "\nOpt-in covers future matches. Turning analysis off stops future "
        "generation; removal is available in /profile.",
        panel,
    )


async def show_history(interaction, client, user, *, topic="", days=0):
    panel = Panel(client, str(interaction.user.id))

    async def filters(request):
        async def submitted(item, values):
            count = number(values["days"], "Days")
            if count < 0:
                raise ArenaError(
                    "The history time filter must be zero or a positive whole number of days."
                    " Enter 30 for the last 30 days, or 0 for all time, then submit the "
                    "filter form again."
                )
            await show_history(item, client, user, topic=values["topic"], days=count)

        await request.response.send_modal(
            Form(
                panel,
                "Filter public match history",
                [
                    Field("topic", "Topic contains", topic, required=False, max_length=100),
                    Field("days", "Past days (0 = all time)", str(days), max_length=6),
                ],
                submitted,
            )
        )

    panel.button("Filter history", filters)
    await safe(
        interaction,
        client.arena.history(
            str(interaction.guild_id),
            user,
            topic,
            client.arena.clock() - days * 86400 if days else 0,
        ),
        panel,
    )


async def show_leaderboard(
    interaction, client, *, topic="", days=0, format_name="", minimum_matches=1
):
    panel = Panel(client, str(interaction.user.id))

    async def filters(request):
        async def submitted(item, values):
            period = number(values["days"], "Days")
            minimum = number(values["minimum"], "Minimum matches")
            if period < 0 or minimum < 1:
                raise ArenaError(
                    "The leaderboard filters need a nonnegative whole number of days and at "
                    "least one minimum match. For example, enter 30 days and 1 minimum match,"
                    " or use 0 days for all time. Correct those fields and submit the filter "
                    "form again."
                )
            await show_leaderboard(
                item,
                client,
                topic=values["topic"],
                days=period,
                format_name=values["format"],
                minimum_matches=minimum,
            )

        await request.response.send_modal(
            Form(
                panel,
                "Filter competitive standings",
                [
                    Field("topic", "Topic contains", topic, required=False, max_length=100),
                    Field("days", "Past days (0 = all time)", str(days), max_length=6),
                    Field(
                        "format",
                        "Format (blank = all)",
                        format_name,
                        required=False,
                        max_length=100,
                    ),
                    Field(
                        "minimum", "Minimum completed matches", str(minimum_matches), max_length=6
                    ),
                ],
                submitted,
            )
        )

    panel.button("Filter standings", filters)
    await safe(
        interaction,
        leaderboard(
            client.arena.repo,
            str(interaction.guild_id),
            topic,
            client.arena.clock() - days * 86400 if days else 0,
            format_name,
            minimum_matches,
        ),
        panel,
    )
