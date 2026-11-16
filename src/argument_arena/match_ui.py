"""Private challenge drafts and permission-aware match navigation."""

import asyncio
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field

import discord

from argument_arena.arena import MAX_CLAIM_LENGTH, require_staff, validate_debate
from argument_arena.messages import MISSING_ROUTES, PROPOSAL_CHANGED, job_guidance
from argument_arena.repository import encode
from argument_arena.settings import ArenaError, match_settings
from argument_arena.settings_ui import DEPENDENCIES, FEATURES, SettingsTarget, show_settings
from argument_arena.ui import Confirm, Field, Form, Panel, actor, number, respond, safe, text


def has_long_claim(match):
    return len(discord.utils.escape_markdown(match["positions"][0])) > 700


async def show_full_claim(interaction, claim):
    await respond(interaction, discord.Embed(title="Challengers Claim", description=claim))


def summary(match, *, draft=False):
    settings = match["settings"]
    embed = discord.Embed(
        title="Review your challenge" if draft else f"Match · {match['state'].title()}",
        description=text(match.get("topic") or "Add the challenger's claim to continue.", 700),
    )
    for index, player in enumerate(match["players"]):
        embed.add_field(
            name=f"Position {index + 1} · member {player}",
            value=text(match["positions"][index] or "Not set", 700),
            inline=False,
        )
    turns = settings["turns"]
    embed.add_field(
        name="Format",
        value=("Alternating turns" if turns["enabled"] else "Flexible order")
        + (
            " · submit each turn"
            if turns["enabled"] and turns["structure"] == "submit"
            else " · messages advance turns"
        )
        + f"\n{'Ranked' if settings['ranked']['enabled'] else 'Casual'}"
        + f" · revision {match['revision']}",
        inline=False,
    )
    clock = (
        f"{settings['inactivity']['hours']} hours after a required speaker is designated"
        if settings["inactivity"]["enabled"]
        else "No response deadline"
    )
    limits = settings["limits"]
    embed.add_field(
        name="Clock and limits",
        value=clock
        + (
            f"\nUp to {limits['rounds']} rounds, {limits['messages']} messages; "
            f"{limits['characters']} characters per message."
            if limits["enabled"]
            else "\nNo automatic round/message limit."
        ),
        inline=False,
    )
    embed.add_field(
        name="Features",
        value="\n".join(
            f"{FEATURES[name]}: {'on' if value['enabled'] else 'off'}"
            for name, value in settings.items()
        ),
        inline=False,
    )
    embed.add_field(
        name="Review before confirming",
        value="Use Features to review every parameter, including rubric weights, privacy "
        "and provider limits. " + DEPENDENCIES,
        inline=False,
    )
    if not draft:
        embed.add_field(
            name="Confirmed this revision",
            value=", ".join(match["confirmed"]) or "Neither participant",
            inline=False,
        )
        if match.get("next"):
            embed.add_field(name="Next required speaker", value=f"<@{match['next']}>")
        if match.get("deadline"):
            embed.add_field(
                name="Exact response deadline",
                value=f"<t:{int(match['deadline'])}:F> · <t:{int(match['deadline'])}:R>",
            )
        if match.get("proposal"):
            proposal = match["proposal"]
            embed.add_field(
                name="Pending agreement",
                value=f"Member {proposal['by']} proposes {proposal['action']}: "
                f"{text(proposal['data'], 300)}. The opponent must agree to these exact terms.",
                inline=False,
            )
        if match.get("channel"):
            embed.add_field(name="Debate channel", value=f"<#{match['channel']}>")
    embed.add_field(name="Started from", value=match["origin"], inline=False)
    if has_long_claim(match):
        embed.set_footer(text="Claim preview. Choose Read full claim to review the complete text.")
    return embed


@dataclass
class Draft:
    client: object
    owner: str
    opponent: str
    origin: str
    settings: dict
    presets: dict
    topic: str = ""
    positions: list = field(default_factory=lambda: ["", ""])
    revision: int = 1
    created: float = field(default_factory=time.monotonic)
    state: str = "editing"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def check(self, revision=None):
        if self.state != "editing" or time.monotonic() - self.created >= 900:
            raise ArenaError(
                "This setup was sent, cancelled or expired and can no longer be changed. If "
                "you already sent it, open `/match` to find the saved challenge. Unsent "
                "drafts expire after 15 minutes or a bot restart and create no match channel;"
                " start a new `/challenge @member` to try again."
            )
        if revision is not None and revision != self.revision:
            raise ArenaError(
                "Your draft changed after this panel was opened, so this action was not "
                "applied to an older version. Use the newest setup summary to review the "
                "claim and Features before sending. If you no longer have that "
                "panel, start a fresh `/challenge @member`."
            )

    def snapshot(self):
        return {
            "players": [self.owner, self.opponent],
            "origin": self.origin,
            "topic": self.topic,
            "positions": list(self.positions),
            "settings": deepcopy(self.settings),
            "revision": self.revision,
        }


def debate_fields(match):
    return [
        Field(
            "claim",
            "Challengers Claim",
            match["positions"][0],
            min_length=3,
            max_length=MAX_CLAIM_LENGTH,
            paragraph=True,
        ),
    ]


def debate_details(claim):
    positions = [claim, "Challenges the claim."]
    validate_debate(claim, positions)
    return claim, positions


class DraftView(Panel):
    def __init__(self, draft):
        super().__init__(draft.client, draft.owner)
        self.draft, self.revision = draft, draft.revision
        self.button("Edit challenger's claim", self.edit, row=0)
        self.button("Features and parameters", self.features, row=0)
        if has_long_claim(draft.snapshot()):
            self.button("Read full claim", self.full_claim, row=0)
        self.button("Send challenge", self.send, style=discord.ButtonStyle.success, row=1)
        self.button("Cancel setup", self.cancel, style=discord.ButtonStyle.danger, row=1)
        self.select(
            "Choose a preset (replaces feature settings)",
            [discord.SelectOption(label=name[:100], value=name) for name in draft.presets],
            self.preset,
            row=2,
        )

    async def edit(self, interaction):
        self.draft.check(self.revision)

        async def save(request, values):
            async with self.draft.lock:
                self.draft.check(self.revision)
                self.draft.topic, self.draft.positions = debate_details(values["claim"])
                self.draft.revision += 1
            await show_draft(request, self.draft)

        await interaction.response.send_modal(
            Form(self, "Challengers Claim", debate_fields(self.draft.snapshot()), save)
        )

    async def features(self, interaction):
        self.draft.check()
        await show_settings(interaction, SettingsTarget(self.client, self.owner, draft=self.draft))

    async def full_claim(self, interaction):
        self.draft.check()
        await show_full_claim(interaction, self.draft.positions[0])

    async def preset(self, interaction, name):
        async with self.draft.lock:
            self.draft.check(self.revision)
            self.draft.settings = match_settings(self.draft.presets[name])
            self.draft.revision += 1
        await show_draft(interaction, self.draft)

    async def cancel(self, interaction):
        async with self.draft.lock:
            self.draft.check()
            self.draft.state = "cancelled"
        self.stop()
        await respond(interaction, "Setup cancelled. No challenge or debate channel was created.")

    async def send(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.draft.lock:
            self.draft.check(self.revision)
            validate_debate(self.draft.topic, self.draft.positions)
            match = await self.client.arena.challenge(
                actor(interaction),
                self.draft.opponent,
                self.draft.topic,
                self.draft.positions,
                self.draft.origin,
                settings=self.draft.settings,
            )
            self.draft.state = "sent"
        self.stop()
        await show_match(interaction, self.client, match["id"])


async def show_draft(interaction, draft):
    draft.check()
    await respond(interaction, summary(draft.snapshot(), draft=True), DraftView(draft))


async def start_challenge(interaction, client, member):
    who = actor(interaction)
    if member.bot or who.bot or str(member.id) == who.id:
        raise ArenaError(
            "A challenge needs two different human members of this server. Choose someone "
            "other than yourself or a bot with `/challenge @member`. For practice against the"
            " bot, use `/train` → Start practice instead."
        )
    if getattr(getattr(member, "guild", None), "id", interaction.guild_id) != interaction.guild_id:
        raise ArenaError(
            "The selected opponent does not belong to this Discord server. Run `/challenge "
            "@member` here and choose a current server member from Discord's suggestions; "
            "matches cannot span different servers."
        )
    config = await client.arena.config(who.guild)
    if not config["categories"]["active"]:
        raise ArenaError(MISSING_ROUTES)
    draft = Draft(
        client,
        who.id,
        str(member.id),
        f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}",
        match_settings(config["defaults"]),
        {"default": deepcopy(config["defaults"]), **deepcopy(config["presets"])},
    )
    await DraftView(draft).edit(interaction)


ACTIONS = {
    "status": ("Status", "State, speaker, exact deadline and job status"),
    "settings": ("Features", "Review every feature and parameter"),
    "edit": ("Edit challenger's claim", "Propose a new revision; both must reconfirm"),
    "preset": ("Choose a preset", "Replace features and reset both confirmations"),
    "accept": ("Confirm reviewed revision", "Confirm exactly the summary you reviewed"),
    "decline": ("Decline challenge", "Cancel this pending challenge"),
    "submit": ("Submit turn", "Finish your newly posted submit-mode turn"),
    "claims": ("Claims and evidence", "Read the ledger or select a claim to check/dispute"),
    "pause": ("Propose pause", "Opponent must agree; save remaining response time"),
    "resume": ("Propose resume", "Opponent must agree; restore remaining time"),
    "extend": ("Extend deadline", "Propose 1–168 extra hours"),
    "request": ("Request a speaker", "In flexible order, agree who must respond next"),
    "concede": ("Concede now", "Immediate loss; no opponent agreement needed"),
    "finish": ("Propose finish", "Mutual ending; run enabled final judging"),
    "draw": ("Propose draw", "Mutual ending with an agreed draw"),
    "cancel": ("Propose cancellation", "Mutual cancellation; staff can cancel immediately"),
    "agree": ("Agree to pending proposal", "Apply the exact proposal shown in the summary"),
    "result": ("Results", "Judgment, references, ratings and allowed feedback"),
    "dispute": ("Dispute result", "Record a reason and optional supporting source"),
    "vote": ("Audience vote", "Separate opinion; never changes the official result"),
    "staff": ("Moderation", "Authorized audit, retry, archive and result decisions"),
}


def available_actions(match, who, config, now):
    choices = ["status", "settings"]
    player = who.id in match["players"] and not who.bot
    staff = who.staff(config)
    state, settings = match["state"], match["settings"]
    if settings["claims"]["enabled"]:
        choices.append("claims")
    if state == "challenge" and player:
        choices += ["edit", "preset", "accept", "decline"]
    if (
        state == "active"
        and player
        and match["next"] == who.id
        and settings["turns"]["enabled"]
        and settings["turns"]["structure"] == "submit"
    ):
        choices.append("submit")
    if state in {"active", "paused"} and (player or staff):
        choices += ["pause" if state == "active" else "resume", "finish", "draw"]
        if match.get("deadline") is not None or match.get("remaining") is not None:
            choices.append("extend")
        if state == "active" and not settings["turns"]["enabled"]:
            choices.append("request")
        if player:
            choices.append("concede")
    if state != "closed" and (player or staff):
        choices.append("cancel")
    proposal = match.get("proposal")
    if proposal and player and proposal["by"] != who.id:
        choices.append("agree")
    if state in {"judging", "closed"}:
        choices.append("result")
        if player:
            choices.append("dispute")
    audience = settings["audience"]
    if (
        state == "closed"
        and audience["enabled"]
        and match.get("vote_until")
        and now <= match["vote_until"]
        and not who.bot
        and (audience["eligibility"] == "members" or not player)
    ):
        choices.append("vote")
    if staff:
        choices.append("staff")
    return choices


class MatchView(Panel):
    def __init__(self, client, match, who, config, *, expanded=False):
        super().__init__(client, who.id)
        self.match = match
        available = available_actions(match, who, config, client.arena.clock())
        preferred = {
            "challenge": ("accept", "decline", "edit", "settings"),
            "active": ("submit", "agree", "pause", "claims"),
            "paused": ("agree", "resume", "claims", "status"),
            "judging": ("result", "status", "claims"),
            "closed": ("result", "vote", "dispute", "claims"),
        }.get(match["state"], ("status", "settings", "claims"))
        primary = [key for key in preferred if key in available]
        for key in ("status", "settings"):
            if key in available and key not in primary and len(primary) < 4:
                primary.append(key)
        secondary = [key for key in available if key not in primary]
        labels = {"accept": "Confirm challenge", "decline": "Decline", "edit": "Edit setup"}
        self.actions(
            [
                (key, labels.get(key, ACTIONS[key][0]))
                for key in (secondary if expanded else primary)
            ],
            self.selected,
            columns=2,
            styles={
                "accept": discord.ButtonStyle.success,
                "agree": discord.ButtonStyle.success,
                "submit": discord.ButtonStyle.primary,
                "decline": discord.ButtonStyle.danger,
                "concede": discord.ButtonStyle.danger,
                "cancel": discord.ButtonStyle.danger,
            },
        )
        if expanded:
            self.button("Back to match", self.back, row=4)
        elif secondary:
            self.button("More actions", self.more, row=2)
        self.button("Choose another match", self.browse, row=4 if expanded else 2)
        if has_long_claim(match):
            self.button("Read full claim", self.full_claim, row=4 if expanded else 2)

    async def full_claim(self, interaction):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        await show_full_claim(interaction, current["positions"][0])

    async def back(self, interaction):
        await show_match(interaction, self.client, self.match["id"])

    async def more(self, interaction):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        config = await self.client.arena.config(str(interaction.guild_id))
        await respond(
            interaction,
            summary(current),
            MatchView(self.client, current, actor(interaction), config, expanded=True),
        )

    async def browse(self, interaction):
        await show_picker(interaction, self.client)

    async def selected(self, interaction, action):
        current = await self.client.arena.repo.match(self.match["id"], str(interaction.guild_id))
        config = await self.client.arena.config(str(interaction.guild_id))
        if action not in available_actions(
            current, actor(interaction), config, self.client.arena.clock()
        ):
            raise ArenaError(
                "This action is no longer available with the match's current state or your "
                "permissions. The match may have advanced, closed, or changed since you "
                "opened this panel. Reopen `/match` to see current controls and use Status to"
                " check what happened."
            )
        if action == "settings":
            await show_settings(
                interaction, SettingsTarget(self.client, self.owner, match_id=current["id"])
            )
        elif action == "edit":

            async def save(request, values):
                topic, positions = debate_details(values["claim"])
                await self.client.arena.settings(
                    actor(request),
                    current["id"],
                    positions=positions,
                    topic=topic,
                    expected_revision=current["revision"],
                )
                await show_match(request, self.client, current["id"])

            await interaction.response.send_modal(
                Form(self, "Propose challenger's claim", debate_fields(current), save)
            )
        elif action == "preset":
            panel = Panel(self.client, self.owner)
            presets = {"default": config["defaults"], **config["presets"]}

            async def selected(request, name):
                await self.client.arena.settings(
                    actor(request),
                    current["id"],
                    presets[name],
                    expected_revision=current["revision"],
                )
                await show_match(request, self.client, current["id"])

            panel.select(
                "Replace features with a preset",
                [discord.SelectOption(label=name, value=name) for name in presets],
                selected,
            )
            await respond(
                interaction,
                "Choosing a preset resets both confirmations. Review the new summary afterwards.",
                panel,
            )
        elif action == "accept":
            await self.client.arena.accept(
                actor(interaction), current["id"], self.match["revision"]
            )
            await show_match(interaction, self.client, current["id"])
        elif action == "status":
            async with self.client.arena.repo.unit() as unit:
                jobs = await unit.rows(
                    "SELECT kind,state,error,due FROM jobs WHERE match_id=? AND state!='done'",
                    (current["id"],),
                )
            for job in jobs:
                job["explanation"] = job_guidance(job["error"], job["state"])
            await respond(
                interaction,
                {
                    "state": current["state"],
                    "next": current["next"],
                    "deadline_utc": time.strftime(
                        "%Y-%m-%d %H:%M:%S UTC", time.gmtime(current["deadline"])
                    )
                    if current["deadline"]
                    else None,
                    "remaining_seconds": current.get("remaining"),
                    "turns": current["turn"],
                    "proposal": current["proposal"],
                    "jobs": jobs,
                },
                MatchView(self.client, current, actor(interaction), config),
            )
        elif action == "result":
            await safe(
                interaction,
                filtered_result(self.client, current, self.owner),
                MatchView(self.client, current, actor(interaction), config),
            )
        elif action == "claims":
            await show_claims(interaction, self.client, current)
        elif action == "dispute":
            await dispute_form(interaction, self, current, "result")
        elif action == "staff":
            await show_staff(interaction, self.client, current)
        elif action in {"request", "vote"}:
            panel = Panel(self.client, self.owner)

            async def chosen(request, player):
                if action == "vote":
                    await safe(
                        request, self.client.arena.vote(actor(request), current["id"], player)
                    )
                else:
                    await self.lifecycle(request, current, "request", {"speaker": player})

            panel.actions(
                [(player, f"Position {i + 1}") for i, player in enumerate(current["players"])],
                chosen,
                columns=2,
            )
            await respond(
                interaction,
                ACTIONS[action][1]
                + "\n"
                + "\n".join(
                    f"Position {i + 1}: member {player}"
                    for i, player in enumerate(current["players"])
                ),
                panel,
            )
        elif action == "extend":

            async def extend(request, values):
                await self.lifecycle(
                    request, current, "extend", {"hours": number(values["hours"], "Hours")}
                )

            await interaction.response.send_modal(
                Form(
                    self,
                    "Propose a deadline extension",
                    [Field("hours", "Extra hours (1–168)", "24", max_length=3)],
                    extend,
                )
            )
        elif action == "agree":
            proposal = self.match.get("proposal")
            if not proposal or proposal != current["proposal"]:
                raise ArenaError(PROPOSAL_CHANGED)
            await self.lifecycle(
                interaction, current, proposal["action"], proposal["data"], proposal=proposal
            )
        elif action in {"concede", "decline", "cancel", "finish", "draw"}:

            async def confirmed(request):
                await self.lifecycle(request, current, action)

            message = ACTIONS[action][1]
            if actor(interaction).staff(config) and action in {"finish", "draw", "cancel"}:
                message += " Your staff authority applies this immediately; the action is audited."
            await respond(interaction, message, Confirm(self.client, self.owner, confirmed))
        elif action == "submit":
            await self.client.arena.submit(actor(interaction), current["id"])
            await show_match(interaction, self.client, current["id"])
        else:
            await self.lifecycle(interaction, current, action)

    async def lifecycle(self, interaction, match, action, data=None, *, proposal=None):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        await self.client.arena.action(
            actor(interaction), match["id"], action, data, expected_proposal=proposal
        )
        await show_match(interaction, self.client, match["id"])


async def filtered_result(client, match, user):
    data = json.loads(encode(await client.arena.result(match["id"], match["guild"])))
    private = match["settings"]["feedback"]["delivery"] == "private"
    enabled = match["settings"]["feedback"]["enabled"]
    for details in [(data.get("report") or {}).get("participants", {}), data.get("feedback", {})]:
        for member, detail in details.items():
            if not enabled or (private and member != str(user)):
                for key in ("strengths", "needs", "practice", "training", "unanswered"):
                    detail.pop(key, None)
    return data


async def show_match(interaction, client, match_id):
    match = await client.arena.repo.match(match_id, str(interaction.guild_id))
    config = await client.arena.config(str(interaction.guild_id))
    await respond(interaction, summary(match), MatchView(client, match, actor(interaction), config))


class MatchPicker(Panel):
    def __init__(
        self, client, owner, matches, *, page=0, all_matches=False, topic="", selected=None
    ):
        super().__init__(client, owner)
        self.page, self.all_matches, self.topic = page, all_matches, topic
        self.selected = selected
        self.matches = matches
        visible = matches[page * 20 : (page + 1) * 20]
        if visible:
            self.select(
                "Choose a match",
                [
                    discord.SelectOption(
                        label=m["topic"][:100],
                        value=m["id"],
                        description=f"{m['state']} · {m['players'][0]} vs {m['players'][1]}"[:100],
                    )
                    for m in visible
                ],
                self.choose,
                row=0,
            )
        self.button("My matches" if all_matches else "All server matches", self.toggle, row=1)
        self.button("Search topics", self.search, row=1)
        if page:
            self.button("Previous page", self.previous, row=2)
        if (page + 1) * 20 < len(matches):
            self.button("Next page", self.next_page, row=2)

    async def choose(self, interaction, match_id):
        if self.selected:
            await self.selected(interaction, match_id)
        else:
            await show_match(interaction, self.client, match_id)

    async def show(self, interaction, *, page=0, all_matches=None, topic=None):
        await show_picker(
            interaction,
            self.client,
            page=page,
            all_matches=self.all_matches if all_matches is None else all_matches,
            topic=self.topic if topic is None else topic,
            selected=self.selected,
        )

    async def toggle(self, interaction):
        await self.show(interaction, all_matches=not self.all_matches)

    async def previous(self, interaction):
        await self.show(interaction, page=self.page - 1)

    async def next_page(self, interaction):
        await self.show(interaction, page=self.page + 1)

    async def search(self, interaction):
        async def chosen(request, values):
            await self.show(request, topic=values["topic"])

        await interaction.response.send_modal(
            Form(
                self,
                "Search match topics",
                [Field("topic", "Topic contains", self.topic, required=False, max_length=100)],
                chosen,
            )
        )


async def show_picker(interaction, client, *, page=0, all_matches=False, topic="", selected=None):
    who = actor(interaction)
    async with client.arena.repo.unit() as unit:
        rows = await unit.rows(
            "SELECT data FROM matches WHERE guild=? ORDER BY created DESC,id DESC", (who.guild,)
        )
    matches = [json.loads(row["data"]) for row in rows]
    matches = [
        m
        for m in matches
        if (all_matches or who.id in m["players"]) and topic.casefold() in m["topic"].casefold()
    ]
    page = min(max(0, page), max(0, (len(matches) - 1) // 20))
    await respond(
        interaction,
        f"**{'Server' if all_matches else 'Your'} matches** · page {page + 1}\n"
        + (
            "Select a match; no ID is needed."
            if matches
            else "No matches found. Use /challenge @member to start one, or browse server matches."
        ),
        MatchPicker(
            client,
            who.id,
            matches,
            page=page,
            all_matches=all_matches,
            topic=topic,
            selected=selected,
        ),
    )


async def open_matches(interaction, client):
    channel_ids = {
        str(interaction.channel_id),
        str(getattr(getattr(interaction, "channel", None), "parent_id", "")),
    }
    async with client.arena.repo.unit() as unit:
        rows = await unit.rows(
            "SELECT id,channel FROM matches WHERE guild=?", (str(interaction.guild_id),)
        )
    current = next((row["id"] for row in rows if row["channel"] in channel_ids), None)
    if current:
        await show_match(interaction, client, current)
    else:
        await show_picker(interaction, client)


async def dispute_form(interaction, parent, match, target, relation=None):
    async def submitted(request, values):
        await safe(
            request,
            parent.client.assistance.dispute(
                actor(request),
                match["id"],
                target,
                values["reason"],
                values["source"] or None,
                relation,
            ),
        )

    await interaction.response.send_modal(
        Form(
            parent,
            "Explain your dispute",
            [
                Field(
                    "reason", "Why is this wrong?", min_length=10, max_length=3000, paragraph=True
                ),
                Field(
                    "source", "Supporting HTTPS source (optional)", required=False, max_length=2000
                ),
            ],
            submitted,
        )
    )


async def show_claims(interaction, client, match, page=0):
    claims = await client.assistance.claims(match["id"], str(interaction.guild_id))
    panel = Panel(client, str(interaction.user.id))
    page = min(max(0, page), max(0, (len(claims) - 1) // 20))
    visible = claims[page * 20 : (page + 1) * 20]

    async def selected(request, claim_id):
        claim = await client.arena.repo.claim(claim_id, str(request.guild_id))
        current = await client.arena.repo.match(match["id"], str(request.guild_id))
        if claim["match"] != current["id"]:
            raise ArenaError(
                "This claim belongs to another match and cannot be accessed through this "
                "panel. Reopen `/match`, select the debate you want, and open its Claims and "
                "evidence list to choose a claim from that debate."
            )
        actions = Panel(client, str(request.user.id))
        if actor(request).id in current["players"]:
            if (
                current["settings"]["on_demand"]["enabled"]
                and not claim["stale"]
                and claim["kind"] == "factual"
            ):

                async def check(item):
                    await safe(item, client.assistance.check(actor(item), claim_id))

                actions.button("Fact-check this claim", check)

            async def dispute(item):
                await dispute_form(item, actions, current, claim_id)

            actions.button("Dispute this claim", dispute)

            async def relate(item):
                other = Panel(client, str(item.user.id))
                others = [c for c in claims if c["id"] != claim_id]

                async def chosen(req, related):
                    await dispute_form(req, other, current, claim_id, related)

                if not others:
                    await respond(item, "No other claims to link.")
                    return
                # A separate paged claim picker preserves access to all related claims.
                await claim_relation_picker(item, other, others, chosen)

            actions.button("Link a related objection", relate, row=1)
        await respond(request, claim, actions)

    if visible:
        panel.select(
            "Choose a claim",
            [
                discord.SelectOption(
                    label=c.get("quote", c.get("summary", c["id"]))[:100],
                    value=c["id"],
                    description=f"{c['kind']} · {c['status']}"[:100],
                )
                for c in visible
            ],
            selected,
        )
    if page:

        async def previous(request):
            await show_claims(request, client, match, page - 1)

        panel.button("Previous page", previous, row=1)
    if (page + 1) * 20 < len(claims):

        async def next_page(request):
            await show_claims(request, client, match, page + 1)

        panel.button("Next page", next_page, row=1)

    async def ledger(request):
        await safe(request, client.assistance.claims(match["id"], str(request.guild_id)))

    panel.button("Full claim and correction ledger", ledger, row=2)
    await respond(
        interaction,
        f"**Claims · page {page + 1}**\nSelect a quote to read evidence and correction history."
        if claims
        else "No claims recorded yet.",
        panel,
    )


async def claim_relation_picker(interaction, parent, claims, chosen, page=0):
    panel = Panel(parent.client, parent.owner)
    panel.select(
        "Select the related claim",
        [
            discord.SelectOption(label=c.get("quote", c["id"])[:100], value=c["id"])
            for c in claims[page * 20 : (page + 1) * 20]
        ],
        chosen,
    )
    if page:

        async def previous(request):
            await claim_relation_picker(request, parent, claims, chosen, page - 1)

        panel.button("Previous", previous, row=1)
    if (page + 1) * 20 < len(claims):

        async def next_page(request):
            await claim_relation_picker(request, parent, claims, chosen, page + 1)

        panel.button("Next", next_page, row=1)
    await respond(
        interaction, "Choose the claim your objection relates to, then explain it.", panel
    )


async def show_staff(interaction, client, match):
    require_staff(actor(interaction), await client.arena.config(str(interaction.guild_id)))
    panel = Panel(client, str(interaction.user.id))

    async def audit(request):
        require_staff(actor(request), await client.arena.config(str(request.guild_id)))
        async with client.arena.repo.unit() as unit:
            rows = await unit.rows(
                "SELECT * FROM events WHERE match_id=? ORDER BY id", (match["id"],)
            )
        await respond(request, rows)

    async def retry(request):
        await safe(request, client.arena.retry(actor(request), match["id"]))

    panel.button("Audit", audit)
    panel.button("Retry failed work", retry)
    if match["state"] == "closed":

        async def archive(request):
            await safe(request, client.gateway.manual_archive(actor(request), match["id"]))

        panel.button("Archive", archive)
    if match["state"] in {"active", "paused", "judging", "closed"}:

        async def decide(request):
            await staff_outcome(request, panel, match)

        panel.button(
            "Correct result" if match["state"] == "closed" else "Close with staff decision",
            decide,
            row=1,
        )
    await respond(
        interaction,
        "Staff actions are checked at execution and recorded in the audit history.",
        panel,
    )


async def staff_outcome(interaction, parent, match):
    panel = Panel(parent.client, parent.owner)
    outcomes = ["judged", "draw", "concession", "forfeit", "cancelled", "inconclusive"]

    async def selected(request, outcome):
        async def reason(req, winner):
            async def submitted(item, values):
                method = (
                    parent.client.arena.correct
                    if match["state"] == "closed"
                    else parent.client.arena.close_match
                )
                await safe(
                    item, method(actor(item), match["id"], outcome, winner, values["reason"])
                )

            await req.response.send_modal(
                Form(
                    panel,
                    "Explain the staff decision",
                    [
                        Field(
                            "reason",
                            "Reason (recorded in audit)",
                            min_length=10,
                            max_length=2000,
                            paragraph=True,
                        )
                    ],
                    submitted,
                )
            )

        if outcome in {"draw", "cancelled", "inconclusive"}:
            await reason(request, None)
        else:
            winners = Panel(parent.client, parent.owner)
            winners.actions(
                [(p, f"Position {i + 1}") for i, p in enumerate(match["players"])],
                reason,
                columns=2,
            )
            await respond(
                request,
                "This is an explicit staff decision. Choose the winning participant.\n"
                + "\n".join(f"Position {i + 1}: <@{p}>" for i, p in enumerate(match["players"])),
                winners,
            )

    panel.actions([(name, name.title()) for name in outcomes], selected)
    await respond(
        interaction,
        "Choose an outcome, then explain the decision. Ratings are replayed after a correction.",
        panel,
    )
