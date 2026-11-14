# Commands and interaction states

Use commands in the configured server, including a public discussion thread. Responses are ephemeral; large details are attached as JSON. IDs come from challenge/status notices. Category/channel/role selection uses Discord pickers. Match controls also have feature selectors, parameter forms, confirmation and decline buttons. [Product policy](product.md) documents defaults, parameters, providers and outcome semantics.

| Command | Authority and inputs | Result |
| --- | --- | --- |
| `/diagnostic` | Administrator | Version, storage and Gateway latency |
| `/setup` | Administrator; `active`, `completed`, `forfeited`, `cancelled` categories; optional `announcement`, `results`, `moderator` | Saved routes and authority |
| `/settings server` | Everyone can view; Administrator can supply `patch` JSON | Full policy, defaults, presets, usage and model configuration |
| `/settings audit` | Administrator | Server change history |
| `/match challenge` | Human member; `member`, `topic`, `your_position`, `their_position`, optional `preset` | Proposed settings/revision; origin link retained |
| `/match accept` | Participant; `match_id`, `revision` | Confirmation, or stale-revision error; channel creation after both confirm |
| `/match decline` | Participant; `match_id` | Pending challenge cancelled |
| `/match settings` | View: members; edit: participants before acceptance; `match_id`, optional feature `patch` JSON and `positions` JSON array | Effective settings, all 20 feature controls and revision |
| `/match status` | Members; `match_id` | State, settings, exact UTC speaker deadline, proposals and job failures |
| `/match submit` | Required participant; `match_id` | Commit the newly posted submit-mode turn |
| `/match claims` | Members; `match_id`; public ledger must be enabled | Quotes, kinds, relations, evidence/status and complete correction history |
| `/match check` | Participant; `claim_id`; on-demand must be enabled | Queued, pending, not-checkable or budget-limit state |
| `/match dispute` | Participant; `match_id`, claim ID or `result` as `target`, `reason`; optional `source` HTTPS URL, `related_claim` | Audited dispute and eligible recheck |
| `/match pause` | Participant proposal/agreement or staff; `match_id` | Active proposal or paused clock |
| `/match resume` | Participant proposal/agreement or staff; `match_id` | Resume saved remaining response time |
| `/match extend` | Participant proposal/agreement or staff; `match_id`, `hours` 1–168 | Agreed extension |
| `/match request` | Participant proposal/agreement or staff; `match_id`, `speaker`; flexible order only | Explicit required-response deadline |
| `/match concede` | Participant; `match_id` | Immediate concession result |
| `/match draw` | Participant proposal/agreement or staff; `match_id` | Agreed draw |
| `/match finish` | Participant proposal/agreement or staff; `match_id` | Judging pending, or finished without judging |
| `/match cancel` | Participant proposal/agreement or staff; `match_id` | Cancelled result |
| `/match result` | Members; `match_id` | Pending state or result/report/references/deltas; private feedback filtered per recipient |
| `/match archive` | Staff; `match_id`; completed only | Durable archival request |
| `/match correct` | Staff; `match_id`, `outcome`, `reason`, optional participant `winner` | Audited review and chronological rating corrections |
| `/match audit` | Staff; `match_id` | Accepted rules, lifecycle, edits, disputes, moderation and rating changes |
| `/match retry` | Staff; `match_id` | Retry failed jobs after resolving configuration/limits |
| `/match close` | Staff; `match_id`, `outcome`, `reason`, optional participant `winner` | Explicit audited decision for active, paused or judging matches, independent of provider availability |
| `/match history` | Members; optional `member`, `topic`, `days` | Public managed-match records, including casual outcomes, procedural statistics and result links |
| `/match vote` | Eligible human; `match_id`, participant `winner`; enabled voting window | Separate replaceable audience opinion |
| `/leaderboard` | Members; optional `topic`, `days`, `format_name`, `minimum_matches` | Current Elo, filtered records and result links |
| `/profile view` | Owner or public visibility; optional `member` | Consented history, observations, evidence and sample sizes |
| `/profile settings` | Self; optional `analysis`, `visibility`, `training`, `recommendations` | Read/update preferences |
| `/profile remove-insights` | Self | Delete generated observations, disable analysis and block old-job regeneration |
| `/profile correct` | Self; `match_id`, `note`, optional `exclude` | Attached correction or exclusion from aggregates |
| `/train start` | Self; optional `mode`, `difficulty`, `topic`, `fallacy` | Original private exercise; one active session per member |
| `/train fallacy` | Self; `name`, optional `difficulty`, `topic` | Selected-family original practice |
| `/train hint` | Self | Counted optional hint |
| `/train answer` | Self; free-text `explanation` | Durable answer awaiting explanation-based grading |
| `/train current` | Self | Prompt, last feedback, provider/job status |
| `/train progress` | Self | Accuracy, recent changes, per-family records and recommendations |
| `/train library` | Members | Supported names and attribution/reference URLs |
| `/train stop` | Self | Stop current session, retain graded progress |
| `/train retry` | Self | Retry failed grading after provider setup |

Authority is checked again at execution, including components. Only Administrator can change server rules; staff means Administrator or a configured moderator role. Staff lifecycle interventions are recorded. Other guilds, DMs, bot challenges, invalid transitions, disabled features and unavailable providers give explicit errors/states. Private DM failures remain private failed deliveries. They never fall back to public coaching.
