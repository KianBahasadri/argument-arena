# Configuration

`config.py` validates operator environment inputs. `settings.py` validates and
materializes persisted server and match policy. Secret values do not belong in
either policy or documentation.

## Operator environment

| Variable | Meaning and default |
| --- | --- |
| `AA_GUILD_ID` | Required positive unsigned 64-bit Discord guild ID. |
| `AA_DISCORD_TOKEN_FILE` | Required path to a UTF-8 token file. |
| `AA_DATA_DIR` | Writable state directory; `.state` locally. |
| `AA_SYNC_COMMANDS` | `true` by default; accepts `true` or `false`. |
| `AA_LOG_LEVEL` | Standard logging level; `INFO`. |
| `AA_LLM_KEY_FILE` | Optional OpenCode Go key-file path. |
| `AA_SEARCH_KEY_FILE` | Optional Brave key-file path. |
| `AA_LLM_MODEL` | `minimax-m3.1-flash`. |
| `AA_LLM_ENDPOINT` | OpenCode Go Chat Completions endpoint by default. |

The only accepted LLM endpoints are
`https://opencode.ai/inference/go/openai/v1/chat/completions` and
`https://opencode.ai/inference/go/openai/v1/responses`.
Token/key files must contain a single nonempty value, at most 4096 characters,
without internal whitespace. `.env.example` provides names and file references;
the runtime does not automatically load `.env`.

Enable Message Content Intent for the Discord application. The client requests
guilds, guild messages, message content and guild reactions, without the members
intent. All seven slash commands are guild-only and have no arguments: `start`,
`match`, `train`, `profile`, `leaderboard`, `admin` and `help`. Synchronization is
restricted to the configured guild and occurs once per login in `setup_hook`.

## Server administration

`/admin` requires Administrator or a configured moderator role. Only Administrator
can change server configuration, defaults, outputs, routes and moderator roles.
Configured moderators receive match moderation controls. Authority is rechecked
at execution, including after a role is revoked.

**Set up routes** uses category pickers for Active, Completed and Cancelled. All
three must be selected before **Save routes** changes the saved policy. Multiple
routes may share a category. The LFG category is managed separately as described
in [matches](matches.md). The obsolete `categories.forfeited` key is discarded
when validating older saved policies without rewriting the record on read.

**Outputs and roles** chooses optional announcement/results text channels and up
to 25 moderator roles. Omitted selections preserve their saved values; explicitly
empty optional selections clear them. Picked channels and roles must belong to
the same server.

**Default match features** provides feature toggles, presets and typed advanced
parameter controls. Default changes apply to future matches. **Advanced server
policy** accepts a JSON patch for less common policy changes.

Server policy defaults:

| Key | Default |
| --- | --- |
| `categories` | `active`, `completed`, `cancelled`: unset |
| `announcement`, `results` | Unset |
| `moderator_roles` | Empty list |
| `channel_name`, `match_prefix` | `match-{id}`, empty prefix |
| `max_concurrent`, `challenge_cooldown` | 3 open matches; 60 seconds between openings |
| `research_daily`, `llm_daily`, `llm_match` | 100, 200, 100 requests |
| `rating_initial`, `rating_k`, `repeat_opponent_daily` | 1000, 32, 3 |
| `llm_models` | `analyze`, `research`, `training`, `battle`: `default` |

IDs in policy are decimal strings or `null` for unset routes/channels. Channel
templates require `{id}` and otherwise lowercase letters, digits and hyphens.
Prefixes use the same characters and at most 12 characters. Numeric server
allowances accept integers from 1 to 100000.

## Match features

Every feature has an `enabled` switch. The following are the remaining defaults;
`settings.DEFAULTS` is the code source of truth.

| Feature | Enabled | Parameters |
| --- | --- | --- |
| `claims` | Yes | `every=1`, `detail=full` |
| `research` | Yes | `depth=3`, `sources=[]`, `budget=20` |
| `corrections` | Yes | `confidence=0.85`, `delivery=batched` |
| `on_demand` | Yes | `limit=10`, `depth=3` |
| `fallacies` | No | `families=[]`, `every=3` |
| `coaching` | No | `delivery=private`, `every=3` |
| `civility` | Yes | `strictness=normal`, `escalation=notify_staff` |
| `live_scores` | No | `every=5` |
| `judging` | Yes | `rubric=arena-v1`, `model=default`, `tie_threshold=3.0`, `tie_policy=draw` |
| `feedback` | Yes | `detail=full`, `delivery=public` |
| `turns` | Yes | `first=0`, `structure=message` |
| `inactivity` | Yes | `hours=24` |
| `reminders` | Yes | `before_hours=2`, `delivery=channel` |
| `limits` | No | `rounds=10`, `messages=100`, `characters=4000` |
| `reactions` | Yes | `allowed=[]` |
| `threads` | Yes | `create=true`, `close_after=false` |
| `audience` | No | `hours=24`, `eligibility=spectators` |
| `ranked` | No | `preset=ranked-v1` |
| `profiles` | Yes | No additional parameters |
| `archive` | Yes | `lock_threads=false` |

Judging weights are reasoning 25, evidence 20, accuracy 15, engagement 20, clarity
10 and rules 10. All six must be nonnegative integers summing to 100.

Unknown keys and incorrect types are rejected. General numeric match parameters
are bounded to 0–10000; frequencies, durations, depths and message/round/character
counts must be positive. Research depth is at most 10, correction confidence is
0–1, and first-speaker indices are 0 or 1. Text lists allow at most 25 entries of
200 characters each. Enum choices come from `settings.ENUMS` and appear in menus.

Disabling research disables corrections. Disabling judging disables ranked play.
Enabled reminders must precede the response window. `ranked-v1` requires its
shared judging, coaching, live-score, turn, inactivity and limit settings.

Built-in presets are casual, ranked, research-off and coaching. Presets replace
feature settings; ranked enables the default limits. The server can save up to
20 presets with names of 1–40 characters. Presets remain available for server
defaults and legacy challenge negotiation. For new match behavior, see
[matches](matches.md); provider selection is covered in [AI services](ai-services.md).
