"""Actionable Discord guidance. External exception text is never shown to members."""

import logging
import math
import uuid

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

SERVER_REQUIRED = (
    "This bot works only in its configured Discord server. Open a text channel or "
    "discussion thread in that server and run the command there; direct messages "
    "and other servers cannot access its matches or settings."
)
ADMIN_REQUIRED = (
    "Administrator permission required. This action changes server-wide bot settings. "
    "Ask someone with Discord's Administrator permission to open `/admin` and make "
    "the change. A configured bot moderator role allows match moderation, not server setup."
)
STAFF_REQUIRED = (
    "Administrator or a configured moderator role required. Ask a server administrator "
    "or bot moderator to manage this match through `/admin` → Moderate a match. "
    "Administrators can choose moderator roles in `/admin` → Output channels and moderator roles."
)
ROUTES_HELP = (
    "Categories are Discord folders that hold match channels.\n"
    "• **LFG:** new channels waiting for a claim and a challenger; created automatically.\n"
    "• **Active:** debates in progress.\n"
    "• **Completed:** finished debates, including concessions and forfeits.\n"
    "• **Cancelled:** debates called off without a competitive result.\n\n"
    "Create the categories in Discord first, select all three below, then click "
    "**Save routes**. You can select the same category more than once, including "
    "one category for everything. Existing saved choices stay in place until you save."
)
MISSING_ROUTES = (
    "Match setup is incomplete: the bot does not know which Discord category should "
    "hold active debate channels. A category is a folder in your server's channel list.\n\n"
    "**How to fix it:** A server administrator must create or choose the categories, "
    "open `/admin` → **Set up routes**, select Active, Completed and Cancelled, then "
    "click **Save routes**. The same category can be used for all three. "
    "Completed also receives forfeited matches.\n\n"
    "After saving, run `/start` again. No match has been created yet."
)
RULES_LOCKED = (
    "Match rules are locked. New LFG matches use the server defaults. You can review "
    "Features in `/match`; administrators can change defaults for future matches in "
    "`/admin`. Legacy challenges awaiting confirmation can still be edited. "
    "Use `/start` to open a new match. If you also want to end an ongoing "
    "match, propose cancellation through `/match`."
)
PROPOSAL_CHANGED = (
    "The proposal changed after this panel was opened. Your agreement was not applied "
    "to different terms. Reopen `/match`, read the newest pending proposal, and choose "
    "Agree only if you accept those exact terms."
)
PANEL_OWNER = (
    "This is another member's private panel, so you cannot use its controls. "
    "Run the relevant slash command yourself, such as `/match`, `/train` or `/profile`, "
    "to open a panel with your own permissions."
)
PANEL_EXPIRED = (
    "This panel expired or has already finished. Menus and forms stay usable for "
    "15 minutes and also stop working after a bot restart. Reopen the relevant slash "
    "command for fresh controls. Saved matches and training progress remain available; "
    "an unsent challenge draft must be created again."
)


def interaction_error(error):
    """Describe known Discord failures; correlate unknown ones without logging payloads."""
    if isinstance(error, discord.Forbidden):
        return (
            "Discord refused this action because the bot does not have permission. "
            "Ask a server administrator to check the bot's role and the permissions "
            "on the affected category or channel, including View Channel and any "
            "posting or channel-management permission needed for this action. "
            "Then reopen the command and check the current status before retrying."
        )
    if isinstance(error, discord.NotFound):
        return (
            "Discord could not find an item needed for this action. A channel, message "
            "or server member may have been removed, or the interaction may have expired. "
            "Reopen the command and select a current item. If a configured match category "
            "was deleted, ask an administrator to update `/admin` → Set up routes."
        )
    if isinstance(error, discord.HTTPException):
        return (
            "Discord could not complete this request. This can happen during a connection "
            "problem or service interruption. Wait a moment, reopen the command and check "
            "its current status before trying again; part of the action may already have "
            "been saved. If it keeps happening, ask the bot operator to check connectivity."
        )
    if isinstance(error, app_commands.CommandOnCooldown):
        return (
            f"This command is on cooldown. Wait {math.ceil(error.retry_after)} seconds "
            "before running it again; repeated attempts do not shorten the wait."
        )
    if isinstance(error, app_commands.BotMissingPermissions):
        return (
            "The bot is missing Discord permissions required for this command. "
            "Ask a server administrator to check the bot's role and channel permissions, "
            "then reopen the command and try again."
        )
    if isinstance(error, app_commands.MissingPermissions):
        return ADMIN_REQUIRED
    if isinstance(error, app_commands.NoPrivateMessage):
        return SERVER_REQUIRED
    if isinstance(error, app_commands.TransformerError):
        return (
            "Discord could not resolve a command option. The selected member or channel "
            "may no longer be available. Enter the command again and choose a current "
            "member or channel from Discord's suggestions."
        )
    if isinstance(error, app_commands.CheckFailure):
        return (
            "This command is not available with your current permissions or server context. "
            "Run it in the configured server. If it is an administration action, ask a "
            "server administrator or configured moderator to use `/admin`."
        )
    reference = uuid.uuid4().hex[:12]
    logger.error(
        "interaction_failed reference=%s",
        reference,
        exc_info=(type(error), error, error.__traceback__),
    )
    return (
        "I could not finish this action because an unexpected error occurred. "
        "Reopen the command and check its current status before retrying; part of "
        "the action may already have been saved. If it keeps failing, ask the bot "
        f"operator to check the logs and share reference `{reference}`."
    )


def failure_reason(status):
    """Translate stored status codes, never arbitrary external text, into next steps."""
    reasons = {
        "not_configured": (
            "The required AI or search service is not configured. Ask the bot operator to"
            " configure the existing OpenCode Go or search integration."
        ),
        "credential_unavailable": (
            "The bot could not read a required service key. Ask the bot operator to check"
            " its mounted credential file without sharing the key in Discord."
        ),
        "credential_rejected": (
            "The service rejected the bot's API key. Ask the bot operator to verify or "
            "replace the key; do not paste it into Discord."
        ),
        "insufficient_balance": (
            "The service refused the request because its allowance or balance was "
            "insufficient. Ask the operator to check the existing OpenCode Go or free "
            "search allowance. No paid fallback or extra usage is enabled."
        ),
        "access_denied": (
            "The service denied access. Ask the bot operator to check the existing "
            "account's access to the configured Go model or search service."
        ),
        "rate_limited": (
            "The service is temporarily rate-limiting requests. Wait for its request "
            "allowance to recover before retrying."
        ),
        "network_failed": (
            "The bot could not reach the service or the request timed out. Wait a moment;"
            " if this continues, ask the operator to check connectivity."
        ),
        "dns_failed": (
            "The bot could not resolve a service or source website's address. Wait a "
            "moment; if this continues, ask the operator to check DNS and connectivity."
        ),
        "http_failed": (
            "The service or source website rejected the request or returned an error. If "
            "retries keep failing, ask the operator to check the integration or use "
            "another evidence source."
        ),
        "model_not_enabled": (
            "The requested model is not enabled. Every AI feature must use the configured"
            " MiniMax M3.1 Flash model through OpenCode Go. Ask an administrator to "
            "restore the feature's model setting to default."
        ),
        "unsupported_api_endpoint": (
            "The AI endpoint is not an allowed OpenCode Go endpoint. Ask the bot operator"
            " to correct the deployment configuration; requests will not fall back to "
            "another provider."
        ),
        "input_limit_exceeded": (
            "This request exceeds the AI input-size limit. Ask a moderator to review the "
            "affected work; retrying the same oversized request will not reduce it."
        ),
        "response_too_large": (
            "The service or source page exceeded the response-size limit. Retrying the "
            "same source may fail again; use a smaller evidence source or ask the "
            "operator to review the work."
        ),
        "provider_redirect_refused": (
            "The service redirected an authenticated request, so the bot stopped to "
            "protect its key. Ask the operator to check the configured service endpoint."
        ),
        "unsafe_source_url": (
            "The evidence URL does not point to an allowed public HTTPS source. Use a "
            "public HTTPS page instead of a private-network address or non-HTTPS link."
        ),
        "unsupported_source_type": (
            "The evidence page is not a supported readable text source. Supply a public "
            "HTTPS HTML or text page instead."
        ),
        "too_many_redirects": (
            "The evidence page redirected too many times. Use a direct link to the final "
            "public HTTPS page."
        ),
        "invalid_search_response": (
            "The search service returned an unreadable response. No factual conclusion "
            "was drawn. If it keeps happening, ask the operator to check the search "
            "integration."
        ),
        "budget_limited": (
            "A configured AI or search usage limit was reached. Daily limits reset at "
            "midnight UTC; per-match limits do not reset. Ask an administrator to check "
            "the applicable limit before retrying."
        ),
        "budget_or_policy_limit": (
            "A configured usage limit or match policy blocked this work. Daily limits "
            "reset at midnight UTC; per-match limits do not reset. Ask an administrator "
            "to check the applicable limit or policy before retrying."
        ),
        "waiting_for_evidence": (
            "Judging is waiting for pending evidence checks. Review their status in "
            "`/match` → Status; a moderator can inspect and retry failed checks."
        ),
        "guild_unavailable": (
            "The bot cannot currently access this Discord server. Ask the operator to "
            "check that the bot is connected and still belongs to the configured server."
        ),
        "channel_not_created": (
            "The debate channel has not been created yet. Check `/match` → Status for "
            "channel-creation work and ask a moderator to retry it if it failed."
        ),
        "active_category_unavailable": (
            "The configured Active category is missing or inaccessible. Ask an "
            "administrator to choose an existing category in `/admin` → Set up routes and"
            " check the bot's channel permissions."
        ),
        "archive_category_unavailable": (
            "The configured Completed or Cancelled category is missing or inaccessible. "
            "Ask an administrator to update `/admin` → Set up routes and check the bot's "
            "channel permissions."
        ),
        "discord_unavailable": (
            "Discord could not complete the background action. Ask an administrator to "
            "check the bot's permissions and that the required channels and members still"
            " exist; transient failures are retried automatically."
        ),
        "unknown_job_kind": (
            "This background task is not recognized by the running bot version. Ask the "
            "bot operator to check the deployment and job logs before retrying."
        ),
    }
    if status in reasons:
        return reasons[status]
    if status in {
        "invalid_model_response",
        "invalid_training_grade",
        "ungrounded_battle_turn",
        "ungrounded_claim",
        "invalid_claim_relation",
        "invalid_analysis_tags",
        "ungrounded_fallacy",
        "invalid_research_response",
        "invalid_source_references",
        "ungrounded_verdict",
        "invalid_judging_participants",
        "invalid_judgment",
        "invalid_scores",
        "invalid_rubric",
        "invalid_judgment_references",
        "ungrounded_judgment",
        "invalid_feedback",
        "empty_rubric",
    }:
        return (
            "The AI response failed validation, so it was not accepted as a result. "
            "It may have been incomplete, malformed or unsupported by the supplied evidence. "
            "If retries keep failing, ask a moderator or the bot operator to review the work."
        )
    return (
        "This background task could not be completed. Ask a moderator or the bot operator "
        "to check its status before retrying. Private service responses are not shown here."
    )


def job_guidance(status, state, *, training=False):
    if not status:
        return "This work is queued or in progress. Reopen this panel shortly to check for updates."
    reason = failure_reason(status)
    if state == "pending":
        return reason + " The bot has scheduled another attempt; there is no need to resubmit."
    if state == "running":
        return reason + " Another attempt is in progress. Check back shortly."
    retry = (
        (
            "Open `/train` → Retry failed grading after the cause is resolved. Your saved"
            " answer remains available."
        )
        if training
        else (
            "After resolving the cause, a moderator can open `/admin` → Moderate a match,"
            " select the match, then choose Retry failed work."
        )
    )
    return reason + " " + retry
