"""Shared, private Discord panels and forms; services remain the authority boundary."""

import asyncio
import io
import json
import time
from dataclasses import dataclass

import discord

from argument_arena.messages import PANEL_EXPIRED, PANEL_OWNER, SERVER_REQUIRED, interaction_error
from argument_arena.settings import Actor, ArenaError


def actor(interaction):
    if interaction.guild_id is None:
        raise ArenaError(SERVER_REQUIRED)
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
        raise ArenaError(
            "The advanced settings could not be read. Use quoted setting names, no trailing "
            "commas, and the documented setting names. Reopen `/admin` → Advanced server "
            "policy to correct it. For categories, channels and feature defaults, use the "
            "dedicated buttons and pickers instead."
        ) from None


def number(value, label, *, decimal=False):
    try:
        return float(value) if decimal else int(value)
    except ValueError:
        kind, example = ("number", "0.85") if decimal else ("whole number", "24")
        raise ArenaError(
            f"The {label} field must be a {kind}, such as {example}. "
            "Enter digits without units or commas, then submit the form again. "
            "Check the field label for the permitted range."
        ) from None


def text(value, limit=1000):
    return discord.utils.escape_markdown(str(value))[:limit]


def _words(value):
    return str(value).replace("_", " ")


def _plain(value):
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) >= 2 and stripped[0] in "{[" and stripped[-1] in "}]":
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                return value
            return "Saved details are left out of this view."
        return value
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ", ".join(_plain(item) for item in value) if value else "none"
    if isinstance(value, dict):
        return ", ".join(f"{_words(key)} {_plain(item)}" for key, item in value.items())
    return str(value)


def _when(timestamp):
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(timestamp))


def _events(rows):
    if not rows:
        return "No audit events yet."
    shown = rows[-30:]
    lines = ["Audit history"]
    if len(rows) > len(shown):
        lines.append(f"Showing the latest {len(shown)} of {len(rows)}.")
    for row in shown:
        who = f"member {row['actor']}" if row.get("actor") else "the bot"
        lines.append(f"{_when(row['created'])} — {_words(row['kind'])} by {who}.")
    return "\n".join(lines)


def _claims(rows):
    if not rows:
        return "No claims recorded yet."
    lines = [f"{len(rows)} claims"]
    for claim in rows[:20]:
        lines.append(f"- {claim.get('quote') or claim.get('summary') or 'Claim'}")
        kind = _words(claim.get("kind", "claim"))
        status = _words(claim.get("status", "recorded"))
        lines.append(f"  {kind}, {status}.")
    if len(rows) > 20:
        lines.append(f"And {len(rows) - 20} more. Use the claim list to open one.")
    return "\n".join(lines)


def _standings(rows):
    if not rows:
        return "No rated matches match these filters."
    lines = ["Standings"]
    for index, row in enumerate(rows, 1):
        lines.append(
            f"{index}. Member {row['user']}: rating {row['rating']}, "
            f"{row['wins']} wins, {row['losses']} losses, {row['draws']} draws."
        )
    return "\n".join(lines)


def _config(config):
    routes = config["categories"]

    def route(name):
        chosen = routes.get(name)
        return f"{name.title()}: " + ("not set" if not chosen else f"category {chosen}")

    roles = config["moderator_roles"]
    return "\n".join(
        [
            "Server setup",
            "LFG: created automatically for new matches.",
            route("active"),
            route("completed"),
            route("cancelled"),
            "Announcements: " + (config["announcement"] or "not set"),
            "Results channel: " + (config["results"] or "not set"),
            "Moderator roles: " + (", ".join(roles) if roles else "none"),
            f"Each member may have {config['max_concurrent']} open matches.",
            f"Match creation cooldown: {config['challenge_cooldown']} seconds.",
            f"Daily research limit: {config['research_daily']}.",
            f"Daily model limit: {config['llm_daily']}. Per match: {config['llm_match']}.",
            f"Starting rating {config['rating_initial']}, step {config['rating_k']}.",
            f"Repeat opponents allowed per day: {config['repeat_opponent_daily']}.",
            "Presets: " + ", ".join(config["presets"]) + ".",
            "Open Default match features to review each default setting.",
        ]
    )


def _status(data):
    lines = [f"This match is {data['state']}."]
    lines.append(
        f"Next speaker: member {data['next']}." if data.get("next") else "No required speaker."
    )
    if data.get("deadline_utc"):
        lines.append(f"Deadline: {data['deadline_utc']}.")
    elif data.get("remaining_seconds") is not None:
        lines.append(f"Clock paused with {data['remaining_seconds']} seconds remaining.")
    else:
        lines.append("No response deadline is running.")
    lines.append(f"Completed turns: {data['turns']}.")
    proposal = data.get("proposal")
    if proposal:
        extra = proposal.get("data") or {}
        detail = ""
        if isinstance(extra, dict) and "hours" in extra:
            detail = f" for {extra['hours']} hours"
        elif isinstance(extra, dict) and "speaker" in extra:
            detail = f" naming member {extra['speaker']}"
        who = f" from member {proposal['by']}" if proposal.get("by") else ""
        lines.append(f"Pending proposal: {_words(proposal.get('action', 'change'))}{detail}{who}.")
    else:
        lines.append("No proposal is waiting.")
    jobs = data.get("jobs") or []
    if jobs:
        lines.append("Background work:")
        for job in jobs:
            lines.append(
                f"- {_words(job.get('kind', 'work'))} is {job.get('state', 'unknown')}. "
                f"{job.get('explanation') or ''}".rstrip()
            )
    else:
        lines.append("No unfinished background work.")
    return "\n".join(lines)


def _history(data):
    stats = data["statistics"]
    lines = [
        "Public match record.",
        (
            f"Wins {stats['wins']}, losses {stats['losses']}, draws {stats['draws']}, "
            f"forfeits {stats['forfeits']}, cancelled {stats['cancelled']}, "
            f"inconclusive {stats['inconclusive']}."
        ),
    ]
    matches = data.get("matches") or []
    if not matches:
        lines.append("No matching debates.")
    for item in matches[:15]:
        outcome = _words(item.get("outcome") or item.get("state") or "open")
        lines.append(f"- {item.get('topic', 'Debate')}: {outcome}.")
    if len(matches) > 15:
        lines.append(f"And {len(matches) - 15} more.")
    return "\n".join(lines)


def _profile(data):
    rating = data.get("current_competitive_rating")
    lines = [
        f"Profile for member {data.get('user', 'this member')}.",
        "Rating: " + ("not rated yet." if rating is None else f"{rating}."),
        f"Matches used for insights: {data.get('sample_matches', 0)}.",
        f"Claims sampled: {data.get('sample_claims', 0)}.",
    ]
    themes = data.get("themes")
    if isinstance(themes, str):
        lines.append(themes)
    elif isinstance(themes, dict):
        shown = [f"{name} {count}" for name, count in themes.items() if count]
        lines.append("Topic types: " + (", ".join(shown) if shown else "none yet") + ".")
    for title, key in (
        ("Strengths", "strengths"),
        ("Practice needs", "practice_needs"),
    ):
        values = data.get(key) or []
        if values:
            lines.append(f"{title}: " + "; ".join(map(str, values[:5])) + ".")
    recommendations = data.get("recommendations") or []
    if recommendations:
        lines.append("Suggested practice: " + ", ".join(map(str, recommendations)) + ".")
    training = data.get("training")
    if training == "Not shared":
        lines.append("Training progress is not shared.")
    elif isinstance(training, dict):
        lines.append(f"Training attempts shared: {training.get('attempts', 0)}.")
    if data.get("policy"):
        lines.append(data["policy"])
    return "\n".join(lines)


def _progress(data):
    lines = [
        f"{data.get('attempts', 0)} completed exercises.",
        f"Suggested difficulty: {data.get('suggested_difficulty', 1)}.",
    ]
    recommendations = data.get("recommendations") or []
    if recommendations:
        lines.append("Practice next: " + ", ".join(map(str, recommendations)) + ".")
    for name, scores in (data.get("by_fallacy") or {}).items():
        recent = scores.get("recent", 0)
        attempts = scores.get("attempts", 0)
        lines.append(f"{_words(name)}: {attempts} attempts, recent score {recent:.0%}.")
    return "\n".join(lines)


def _result(data):
    if data.get("message") and "outcome" not in data:
        return data["message"]
    winner = data.get("winner")
    lines = [
        f"Outcome: {_words(data.get('outcome', 'unknown'))}.",
        "Winner: " + (f"member {winner}." if winner else "none."),
    ]
    if data.get("reason"):
        lines.append(str(data["reason"]))
    if "rated" in data:
        lines.append(
            "This match changed ratings." if data["rated"] else "This match did not change ratings."
        )
    changes = data.get("rating_changes") or {}
    if changes:
        parts = [
            f"member {player} {before} to {after}" for player, (before, after) in changes.items()
        ]
        lines.append("Rating changes: " + ", ".join(parts) + ".")
    votes = data.get("audience_votes") or {}
    if any(votes.values()):
        parts = [f"member {player} {count}" for player, count in votes.items()]
        lines.append("Audience votes: " + ", ".join(parts) + ".")
    report = data.get("report") or {}
    for member, detail in (report.get("participants") or {}).items():
        scores = detail.get("scores") or {}
        if scores:
            bits = ", ".join(f"{_words(name)} {score}" for name, score in scores.items())
            lines.append(f"Member {member} scores: {bits}.")
        for title, key in (("Strengths", "strengths"), ("To improve", "needs")):
            values = detail.get(key) or []
            if values:
                notes = "; ".join(map(str, values[:4]))
                lines.append(f"{title} for member {member}: {notes}.")
    lines.append("A result does not prove that a claim is true.")
    return "\n".join(lines)


def _feature(name, values):
    lines = [_words(name).title(), "On" if values.get("enabled") else "Off"]
    for key, value in values.items():
        if key == "enabled":
            continue
        lines.append(f"{_words(key).title()}: {_plain(value)}.")
    return "\n".join(lines)


def _claim(claim):
    lines = [
        claim.get("quote") or claim.get("summary") or "Claim",
        f"{_words(claim.get('kind', 'claim')).title()}, {_words(claim.get('status', 'recorded'))}.",
    ]
    summary = claim.get("summary")
    if summary and summary != claim.get("quote"):
        lines.append(summary)
    if claim.get("author"):
        lines.append(f"Said by member {claim['author']}.")
    disputes = claim.get("disputes") or []
    if disputes:
        lines.append(f"{len(disputes)} dispute{'s' if len(disputes) != 1 else ''} recorded.")
        for item in disputes[-3:]:
            if item.get("reason"):
                lines.append(f"- {item['reason']}")
    else:
        lines.append("No disputes.")
    return "\n".join(lines)


def _rows(value, keys):
    return bool(value) and all(isinstance(item, dict) and keys <= item.keys() for item in value)


def readable(value):
    """Turn stored records into short text. Members never receive raw JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if _rows(value, {"match_id", "kind", "created", "data"}):
            return _events(value)
        if value and all(isinstance(item, dict) and "quote" in item for item in value):
            return _claims(value)
        if _rows(value, {"rating", "wins", "user"}):
            return _standings(value)
        if not value:
            return "Nothing to show."
        lines = []
        for index, item in enumerate(value, 1):
            shown = readable(item) if isinstance(item, dict) else _plain(item)
            lines.append(f"{index}. {shown}")
        return "\n".join(lines)
    if isinstance(value, dict):
        if {"categories", "presets", "max_concurrent"} <= value.keys():
            return _config(value)
        if {"deadline_utc", "jobs", "turns"} <= value.keys():
            return _status(value)
        if {"statistics", "matches"} <= value.keys():
            return _history(value)
        if "sample_matches" in value:
            return _profile(value)
        if "suggested_difficulty" in value:
            return _progress(value)
        if "outcome" in value or ("message" in value and "state" in value):
            return _result(value)
        if len(value) == 1:
            name, inner = next(iter(value.items()))
            if isinstance(inner, dict) and "enabled" in inner:
                return _feature(name, inner)
        if {"quote", "kind", "status"} <= value.keys():
            return _claim(value)
        return "\n".join(f"{_words(key).title()}: {_plain(item)}." for key, item in value.items())
    return _plain(value)


async def respond(interaction, value, view=None):
    kwargs = {"ephemeral": True, "allowed_mentions": discord.AllowedMentions.none()}
    content = None
    if isinstance(value, discord.ui.LayoutView):
        kwargs["view"] = value
    elif isinstance(value, discord.Embed):
        kwargs["embed"] = value
    else:
        content = readable(value)
        if len(content) > 1800:
            kwargs["file"] = discord.File(io.BytesIO(content.encode()), filename="details.txt")
            content = (
                content[:1500].rsplit("\n", 1)[0]
                + "\n\nThe rest is in the attached text file. Only you can see it."
            )
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


class PanelAccess:
    """Shared owner, server and expiry checks for private Discord views."""

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.client.config.guild_id:
            await respond(interaction, "This panel belongs to another server. " + SERVER_REQUIRED)
            return False
        if str(interaction.user.id) != self.owner:
            await respond(interaction, PANEL_OWNER)
            return False
        if self.is_finished():
            await respond(interaction, PANEL_EXPIRED)
            return False
        return True

    async def on_error(self, interaction, error, item):
        await respond(
            interaction,
            str(error) if isinstance(error, ArenaError) else interaction_error(error),
        )


class Panel(PanelAccess, discord.ui.View):
    def __init__(self, client, owner, *, timeout=900):
        super().__init__(timeout=timeout)
        self.client, self.owner = client, str(owner)

    def button(
        self, label, callback, *, style=discord.ButtonStyle.secondary, row=None, custom_id=None
    ):
        item = discord.ui.Button(label=label, style=style, row=row, custom_id=custom_id)

        async def selected(interaction):
            await callback(interaction)

        item.callback = selected
        self.add_item(item)
        return item

    def actions(self, choices, callback, *, row=0, columns=3, styles=None):
        for index, (value, label) in enumerate(choices):

            async def selected(interaction, value=value):
                await callback(interaction, value)

            self.button(
                label,
                selected,
                style=(styles or {}).get(value, discord.ButtonStyle.secondary),
                row=row + index // columns,
                custom_id=f"action:{value}",
            )

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
                await respond(
                    interaction,
                    "This confirmation has already been used or expired. The action will not "
                    "be run again from this button. Reopen the command and check the current "
                    "status before starting another action; a completed confirmation may "
                    "already have taken effect.",
                )
                return
            self.stop()
            await self.operation(interaction)

    async def cancel(self, interaction):
        self.stop()
        await respond(interaction, "No change made. Reopen the menu to continue.")
