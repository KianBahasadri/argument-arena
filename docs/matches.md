# Matches

The match state machine is in `src/argument_arena/arena.py`. Discord side effects
are in `discord_gateway.py`; `match_ui.py` owns private navigation and controls.
See [configuration](configuration.md) for defaults and route setup.

## Opening a match

`/start` has no arguments and opens a channel without an opponent picker, claim
form, draft or acceptance step. `/match` also offers **Start a match** in its
ordinary match browser. Both call `Arena.open_match`.

The initial saved state is `lfg`, with one player, no topic, no next speaker and
no response deadline. Rules are a snapshot of server defaults and are read-only.
The origin channel or thread URL is retained. Opening is restricted to human
members and obeys the server's creation cooldown and concurrent match limit.
The configured active route is required before a match can open.

Channel creation has a durable `create` job and is attempted immediately from the
interaction. A temporary Discord failure leaves the saved match and job available
through `/match` → Status. `DiscordGateway.create` serializes creation attempts,
fetches server channels and uses the topic marker `Argument Arena match:<id>`
to recover a channel created before a database acknowledgment.

The gateway reuses a category named exactly **LFG**, or creates it if absent.
LFG is discovered by name and is not an additional configurable category route.
Channel names use the server's `channel_name` template.

## Claim and challenger

The opener's first nonblank qualifying message becomes the claim. Its trimmed
text must have 3–4000 characters and satisfy any enabled per-message limit.
Other members cannot join before a claim exists. The opener can add context
without starting the battle or a response clock.

Opening messages are stored in the official transcript, but analysis is deferred
until the match has an opponent. Editing the opening claim while waiting updates
the topic and position. Deleting it, or shortening it outside the allowed range,
clears the claim and prevents joining until a valid claim is posted or restored.

The first other human to post a qualifying nonblank reply becomes the opponent.
Joining checks that member's concurrent match limit inside the same serialized
transaction as assigning the seat. Competing replies cannot create a third
participant. Bot posts, blank messages and messages from discussion threads do
not join matches.

Joining changes the state to `active`, records both participants, schedules
analysis for current nondeleted opening messages, and queues an `activate` job.
That job moves the same channel into the configured Active category, used for
ongoing battles, and restricts main-channel posting to the two participants and
staff. It preserves explicit overwrites instead of syncing category permissions.

The initial claim and challenging reply count as the first two completed turns.
With alternating turns enabled, the opener responds next and their response
clock starts at matching. This opening sequence applies even when the inherited
`turns.first` setting is 1. In submit mode, both opening turns are already
submitted; the opener must post a new message before submitting their next turn.
Flexible order starts with no required speaker or response clock.

## Continuing and ending

In message mode, each qualifying official message completes a turn. Submit mode
requires a newly posted official message followed by **Submit turn**. Duplicate,
out-of-turn and over-limit messages do not advance the match. Message edits and
reactions do not reset clocks.

Pause, resume, deadline extensions, finish, draw and cancellation require the
opponent's agreement to the same proposal. A newer proposal invalidates older
agreement controls. An LFG opener can cancel immediately without an opponent.
Concession immediately records a loss in an active or paused match after the
private confirmation button is used. Authorized staff can apply lifecycle
actions immediately; those actions are audited.

Pausing freezes remaining response time. Resuming restores it. Extensions allow
1–168 hours and require an existing deadline or paused time. Flexible matches can
agree on a required speaker through **Request a speaker**.

Enabled round or message limits automatically finish the debate. A round is two
completed turns. Final judging changes the state to `judging`; without judging,
finishing records an inconclusive result. See [AI services](ai-services.md).

The worker emits deadline reminders and records a forfeit when an observed,
connected response deadline expires. LFG channels and legacy pending challenges
expire as cancelled after seven days from creation. LFG waiting time never
causes a competitive forfeit.

Closure locks ordinary main-channel posting. Automatic archival moves cancelled
matches to Cancelled and other outcomes, including concessions and forfeits, to
Completed. Staff can archive a closed match manually. Thread locking follows the
accepted thread/archive settings. Single-player LFG cancellations do not receive
generated profile observations or competitive ratings.

## Permissions, recovery and message revisions

LFG channels allow ordinary roles to post so another member can join. Before the
claim exists, enforcement removes posts from nonparticipants other than staff.
Active channels explicitly deny main-channel posting on every ordinary role;
member overwrites allow the two players. Configured moderator roles and the bot
retain management access. Discord administrators retain their platform authority.
Reactions and thread permissions follow the saved features.

The client enforces posting policy before recording a message and rechecks
rejected messages so a losing simultaneous challenger cannot remain as a third
speaker. Recorded final messages remain in place when they finish the match.
New-role and server-policy changes queue permission restoration.

On reconnect, reconciliation reads channel history oldest-first. It first repairs
edits/deletions of saved messages, then ingests missed posts, including unknown
challengers in LFG. This prevents a deleted or outdated saved claim from admitting
a challenger. Official message IDs make replay idempotent.

Saved message revisions mark earlier extracted claims stale. Changes after a
completed result flag it for staff review, remove affected generated insights and
replay ratings. Deleted active channels pause the response clock for staff
resolution. During outages or worker gaps longer than 60 seconds, deadlines are
extended by the unobserved interval before forfeit checks. Reconciliation must
succeed before the worker resumes connected deadline processing.

## Existing challenges

The older `challenge` → `starting` → `active` state path and its private draft and
settings helpers remain supported for existing records and compatibility tests.
Legacy challenges require both participants to confirm the same revision; edits
clear confirmations. The public `/challenge @member` command has been replaced
by `/start`.

`/match` opens the current channel's match, including from its discussion threads,
or a paginated browser of personal/server matches with a topic filter. Panels
offer only actions available to the viewer and current state; services recheck
authorization when controls are used.
