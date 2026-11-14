# Configuration and operating choices

## Runtime

The runtime reads environment variables; it does not automatically load a tracked configuration or `.env` file. `.env.example` lists supported values. Use a private environment file, your shell's secret loader, or the Kubernetes Secret described in [deployment](deployment.md).

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Required bot token |
| `DISCORD_GUILD_ID` | Intended server ID; registers commands there and rejects other guilds |
| `DATABASE_PATH` | SQLite file; default `data/arena.sqlite3`, `/data/arena.sqlite3` in the image |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | OpenAI-compatible HTTPS provider credentials, endpoint and model |
| `RESEARCH_API_KEY`, `RESEARCH_BASE_URL` | Tavily credentials and HTTPS endpoint |
| `DAILY_LLM_CALLS`, `DAILY_RESEARCH_CALLS` | Global daily request quotas, default 500 and 100 |
| `DAILY_LLM_BUDGET_USD` | Optional monetary cap; zero disables it |
| `LLM_INPUT_COST_PER_MILLION`, `LLM_OUTPUT_COST_PER_MILLION` | Operator-supplied model prices needed for dollar caps |
| `LLM_MAX_INPUT_BYTES`, `LLM_MAX_OUTPUT_TOKENS` | Bounded model input and output, default 120000 bytes and 3000 tokens |
| `LLM_TOKEN_PARAMETER` | `max_completion_tokens`, or `max_tokens` for compatible alternative providers |

The default model name is a configurable example, not a promise of account availability or provider pricing. With multiple models, configure prices conservatively for the most expensive permitted model. Call quotas reserve before network requests; failed requests consume quota. Dollar reservations conservatively count input bytes and maximum output tokens and are not invoices. Usage is retained in `usage` and `provider_calls` records.

## Server administration

`/setup` requires an administrator and records category/channel IDs and an optional moderator role. `/settings server` supports a JSON patch. The persisted server fields are `moderator_role_ids`, `active_category_id`, `completed_category_id`, `forfeited_category_id`, `cancelled_category_id`, `announcement_channel_id`, `results_channel_id`, `max_concurrent`, `challenge_cooldown`, `channel_template`, `defaults`, and `presets`.

For example, `{"max_concurrent":5,"defaults":{"response_hours":48},"presets":{"friendly":{"judging":false,"background_research":false}}}`. Channel templates support `{id}` and `{topic}`. Staff actions are checked again at execution time; Discord's command visibility is not the authorization boundary.

## Match settings

`/match options` lists every supported switch and parameter. `/match settings` accepts JSON with just the keys to change. The current rules and pending proposal remain available for inspection. Both participants confirm the exact proposed rules; a changed proposal invalidates earlier acceptance. Changes to an active match also require agreement.

The switches are `claim_tracking`, `background_research`, `factual_corrections`, `on_demand_checks`, `fallacy_detection`, `coaching`, `civility`, `live_scores`, `judging`, `feedback`, `turn_enforcement`, `inactivity_forfeits`, `deadline_reminders`, `limits`, `spectator_reactions`, `discussion_threads`, `audience_voting`, `ranked`, `profile_insights`, and `automatic_archival`.

Parameters cover response/reminder times; round/message/length limits; call/dollar budgets; source preferences and research depth; correction confidence; notification interval; model choices; feedback and coaching delivery; scoring weights and tie threshold; initial speaker; thread archival; audience eligibility and voting window. The exact names and effective defaults are defined once in `arena/core.py` and exposed through `/match options`.

Disabling background research also disables automatic factual corrections. On-demand checks are separately configurable. Claim extraction can continue internally with the public ledger disabled. Disabling judging makes a match unranked. Research failures and budget limits never count as evidence that an author is wrong.

## Results, ratings and deadlines

Turns advance with `/match submit` after the required speaker posts an argument. Ordinary spectator, bot, and opponent activity cannot reset the clock. Flexible-order matches can explicitly designate a required speaker using `/match request`. Both players can agree to a pause, resume, extension, cancellation, draw, or finish; staff can intervene with an audit record. A concession is immediate.

The shared ranked rubric weights reasoning 25%, evidence 20%, accuracy 15%, engagement 20%, clarity 10%, and rules 10%. Dimension scores range from 0 to 100, with draws within three weighted points. If empirical accuracy is unassessed for either participant, that dimension is omitted for both. Insufficient or malformed judgments produce an explicit inconclusive result.

Elo starts at 1200 with K=32. Leaderboard records can be filtered by topic, time and preset with a minimum-match threshold; displayed ratings remain the guild-wide Elo. Ranked judged results, agreed draws, and concessions affect ratings. Forfeits are recorded separately and affect ratings only when both accept `forfeit_rated`. Cancellations, inconclusive results, casual debates, audience votes and training do not affect ratings. Correcting a result replays the guild's ranked history, including downstream changes.

Heartbeat gaps longer than 90 seconds extend active response deadlines by the measured downtime before expiry is evaluated. Paused clocks retain their remaining duration. This is a single-process application; run one replica per database.

## Privacy and evidence

Profiles default to disabled and private. Both the match switch and the user's opt-in must permit analysis. Training recommendations have their own preference. Views expose evidence links and sample sizes and describe positions as argued positions, not personal beliefs. Users can add corrections, revoke consent, and remove generated insights. Changing visibility does not erase copies already downloaded by other people.

Discord messages and source pages are untrusted model input. Models receive no execution tools or credentials. Research separately retrieves public HTTPS HTML/text sources, blocks private/reserved DNS destinations and redirects, limits size/time, and checks citation quotations against inspected text. PDF-only, paywalled, blocked, JavaScript-only and unreadable sources are reported as retrieval failures. The model's interpretation remains reviewable by staff and participants.
