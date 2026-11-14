# Using Argument Arena

Commands run inside the configured Discord server. Most match commands infer the match from its main channel; provide `match_id` when using them elsewhere. Spectators can read permitted reports and issue challenges without ordinary posting access in a match channel. Long reports are attached as JSON files with their evidence rather than truncated.

## Administration

1. Create active, completed, forfeited, and cancelled categories in Discord.
2. Run `/setup` with those categories, an optional moderator role, and optional results/announcement channels.
3. Review `/settings server`; administrators can patch server settings with JSON.
4. Run `/ping` to check the bot's gateway connection.

An administrator can configure the server. Configured moderators can manage matches, archive channels, review disputes and correct results. Changing category membership preserves explicit match permissions. Discord administrators retain Discord's built-in permission bypass.

## Challenge and agree on settings

`/match challenge member:<opponent> topic:<topic>` creates a challenge. Optional arguments specify positions and a preset. Challenges issued in public discussion threads retain a link to their origin. Built-in presets are `casual`, `ranked`, `no-research`, and `coaching`; administrators can add more.

`/match options` lists all available settings. Inspect `/match settings match_id:<id>` and propose changed keys with the `patch` parameter or the settings button. For a first match without external AI calls, use:

```json
{
  "claim_tracking": false,
  "background_research": false,
  "on_demand_checks": false,
  "civility": false,
  "judging": false,
  "feedback": false
}
```

The opponent runs `/match accept match_id:<id>` or presses Accept. Each changed proposal requires both players' confirmation. The bot creates the match channel only after agreement. `/match decline` declines a challenge or pending settings change.

## Debate and research

The required speaker posts in the main channel, then runs `/match submit`. The other participant receives posting access and a response deadline. Everyone can read, react and use discussion threads when the accepted settings allow it. Main-channel moderator messages and all thread messages are excluded from judging.

| Command | Behavior |
| --- | --- |
| `/match status` | Current state, required speaker, deadline and pending action |
| `/match settings` | Effective feature settings and proposed changes |
| `/match claims` | Attributed claim ledger, source links, checks and revision status |
| `/match check claim_id:C1` | Queue an enabled, budgeted on-demand check or recheck |
| `/match source claim_id:C1 url:<https-url>` | Attach a source for a later check |
| `/match dispute target:C1 reason:<explanation>` | Record a claim dispute for staff |
| `/match dispute target:result reason:<explanation>` | Record a result dispute |
| `/match request member:<participant>` | Agree on the required speaker in flexible-order play |
| `/match vote member:<participant>` | Submit a separately recorded audience vote when enabled |

Research can show pending, complete, stale, unavailable, failed, or budget-limited status. An edited/deleted message invalidates its prior checks. A possible fallacy or civility concern includes quoted text and an explanation; it remains distinguishable from staff moderation. Coaching and feedback follow the accepted delivery setting.

## Pause and finish

`/match pause`, `/match resume`, `/match extend hours:<number>`, `/match draw`, `/match finish`, and `/match cancel` require both participants to request the same action. Configured staff can perform these actions directly. `/match concede` immediately records a loss for the conceding participant.

An expired required-speaker deadline results in a procedural forfeit when enabled. Bot interruptions extend the clock before expiry is checked. A forfeit does not establish that the winner's claims are true.

Finishing a judged match queues analysis after pending evidence work. `/match result` retrieves its report. `/leaderboard` supports topic, recent-day, preset and minimum-match filters and keeps ranked records separate from casual matches, training and audience feedback.

Staff use `/match review match_id:<id>` to inspect audit events, optionally request a fresh proposed judgment, and use `/match correct match_id:<id> reason:<explanation> winner:<member>` to record a reviewed winner. Omitting the winner records a draw. Corrections retain history and rebuild affected ratings. `/match archive` manually moves a finished channel while retaining its intended permissions.

## Training

`/train start` offers spot-the-fallacy, mixed, argument repair, sound-or-fallacious, training battle, and personalized review modes. `/train fallacy name:<fallacy>` focuses on a named fallacy. Choose `easy`, `normal`, or `hard` difficulty and an optional topic.

Use `/train answer text:<explanation>` to identify and explain the reasoning error or submit a repair. Naming a fallacy alone is insufficient. `/train hint` provides help; `/train progress` shows identification and explanation scores, practice history and recommended exercises. Battles run for up to five turns. Explanations and feedback link to the relevant Logically Fallacious reference; the exercises are original.

An LLM provider is required for free-text grading and newly generated/custom exercises. Provider failure records no fabricated grade and permits retry. Curated starting exercises and hints are available without a provider.

## Profiles and privacy

`/profile view` shows your profile; its optional member argument requests an available public profile. Profiles default to private with analysis disabled. To opt in, use `/profile settings` with:

```json
{
  "opt_in": true,
  "visibility": "private",
  "training_recommendations": true
}
```

The match must also enable `profile_insights`. Generated observations cite the author's messages and show sample sizes and dates. They describe argument behavior and positions argued, without asserting psychological diagnoses or personal beliefs. Training analysis is separately controlled with `training_analysis`.

`/profile dispute` records an explanation of a mischaracterization. Corrections to a specific insight can also be submitted through `/profile settings` with `{"correction":{"insight_id":"<id>","text":"<your correction>"}}`. `/profile remove-insights` purges generated insights and disables future analysis; official match results and practice history remain. Profile access rechecks visibility and eligible evidence each time.
