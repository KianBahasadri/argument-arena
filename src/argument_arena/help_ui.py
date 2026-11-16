"""In-Discord guidance for the registered seven-command surface."""

import discord

from argument_arena.ui import Panel, actor, respond

HELP = {
    "start": (
        "Match quick start",
        "1. Run `/start` or choose Start a match in `/match`. A new channel opens "
        "in **LFG** using the server's default rules.\n2. Post your claim in that "
        "channel.\n3. The first other person to reply becomes your challenger. "
        "The channel moves into ongoing battles automatically, and both opening "
        "messages count toward the debate.\n4. Continue debating in the same "
        "channel. Open `/match` for Features, turns, deadlines and controls. "
        "The opener responds next when alternating turns are enabled.\n\n"
        "You can cancel your LFG match while waiting. No response deadline runs "
        "until a challenger joins. Unmatched channels expire after seven days.",
    ),
    "controls": (
        "During a match",
        "Open `/match` in the debate channel (or choose a match from the menu). "
        "Status shows the required speaker, exact deadline and pending work.\n\n"
        "Message mode advances automatically after a qualifying official message. "
        "In submit mode, post your response, then choose Submit turn. "
        "Discussion-thread messages are not official turns.\n\nPause/resume and "
        "deadline extensions require your opponent's agreement. Flexible-order "
        "matches can agree on a required next speaker. Staff interventions are "
        "immediate and audited.\n\nFeatures shows all accepted settings. Accepted "
        "rules are locked.",
    ),
    "end": (
        "Ending a match",
        "**Concede now:** you immediately lose an active or paused match; your "
        "opponent does not need to agree. A confirmation protects against "
        "accidental clicks.\n\n**Propose finish:** both agree to stop debating; "
        "enabled final judging runs. Without judging, the recorded outcome is "
        "inconclusive.\n\n**Propose draw:** both agree to a drawn result.\n\n**Propose "
        "cancellation:** both agree to cancel; authorized staff can cancel "
        "immediately. The opener can cancel an LFG match immediately. Legacy "
        "pending challenges can still be declined by either participant.\n\n"
        "The opponent uses Agree to pending proposal for the exact terms shown. "
        "Results, claims/evidence and permitted feedback are in `/match`. Audience "
        "votes, when enabled, remain separate from judging and ratings.",
    ),
    "automatic": (
        "Automatic endings and deadlines",
        "Agreed round/message limits automatically finish the debate and run "
        "enabled final judging. A round comprises two completed participant turns."
        "\n\nBy default, a **24-hour response deadline** starts only after someone is"
        " explicitly designated the next required speaker. Alternating-turn matches"
        " designate the opener after a challenger joins, then the opponent after "
        "each completed turn. LFG waiting time has no response clock. Flexible "
        "order has no response clock until both agree on a"
        " speaker request (or staff designate one). The accepted response window "
        "can differ from 24 hours or be disabled.\n\nIf the required speaker misses "
        "an enabled deadline, they forfeit. An agreed pause freezes remaining time;"
        " resume restores it. Edits, reactions and discussion messages do not reset"
        " the clock. Status shows the exact deadline. An unreviewed judging failure"
        " does not become a loss; staff can resolve it.",
    ),
    "training": (
        "Training",
        "Open `/train` → Start practice. Choose spot, selected-fallacy, mixed, "
        "battle, repair or sound practice, then difficulty and topic. The library "
        "includes credited reference links.\n\nUse Answer exercise for your "
        "explanation or repair, Request a hint when needed, Current exercise for "
        "prompt/feedback/provider status, and Progress for results and suggestions."
        " Stop session retains completed practice; Retry failed grading uses your "
        "saved answer. Training is private and does not affect ratings.",
    ),
    "profiles": (
        "Profiles and leaderboards",
        "Open `/profile` to view permitted insights, public match history, or "
        "choose another member. Your own panel includes Privacy and consent, "
        "insight corrections/exclusions and removal. Defaults are analysis off, "
        "private visibility and no training sharing. Staff cannot bypass another "
        "member's profile privacy.\n\nOpen `/leaderboard` for competitive standings "
        "and filter by topic, period, format or activity. Public match records and "
        "optional generated insights are separate. Casual play, cancellations, "
        "inconclusive results and training do not change Elo.",
    ),
    "rules": (
        "Server rules",
        "New LFG matches use configured server defaults. Research off also "
        "disables factual corrections; judging "
        "off disables ranked play. Ranked-v1 uses a shared rubric, turns, deadlines"
        " and limits. Reminder lead time must be shorter than the response window. "
        "All AI uses the operator's single OpenCode Go model.\n\nUse Features in "
        "`/match` to inspect every parameter. "
        "Administrators manage defaults and presets in `/admin`. Missing or "
        "unavailable AI reports its state while ordinary match management "
        "continues.",
    ),
    "admin": (
        "Setup and moderation",
        "Open `/admin` → Set up routes to select active, completed and cancelled "
        "categories. Completed includes concessions and forfeits; the same category "
        "can serve multiple routes. The bot creates the **LFG** category automatically "
        "when needed. Output channels and moderator roles are optional. "
        "Administrator is required for configuration, defaults, server audit and "
        "Connection diagnostic. Advanced server policy retains the documented patch"
        " form for unusual policy changes.\n\nConfigured moderators can select a "
        "match and inspect its audit, retry failed work, archive a completed match,"
        " or record an explained closure/correction. Staff lifecycle interventions "
        "are immediate and audited; result corrections replay affected ratings. "
        "These controls recheck current authority when used.",
    ),
}


async def show_help(interaction, client, topic="start"):
    config = await client.arena.config(str(interaction.guild_id))
    topics = [key for key in HELP if key != "admin" or actor(interaction).staff(config)]
    if topic not in topics:
        topic = "start"
    title, description = HELP[topic]
    panel = Panel(client, str(interaction.user.id))

    async def selected(request, key):
        await show_help(request, client, key)

    panel.actions(
        [(key, HELP[key][0]) for key in topics],
        selected,
        columns=2,
        styles={topic: discord.ButtonStyle.primary},
    )
    if topic == "rules":

        async def configuration(request):
            await respond(request, await client.arena.config(str(request.guild_id)))

        panel.button("View server configuration", configuration, row=4)
    embed = discord.Embed(title=title, description=description)
    await respond(interaction, embed, panel)
