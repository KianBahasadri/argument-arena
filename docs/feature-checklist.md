# Feature-to-test and documentation checklist

Every README section and implementation phase is covered below. These are offline implementation checks; they do not assert a live deployment, real model quality or research-provider availability. Run `bash scripts/validate.sh` with the pinned development environment and Docker. The shared CI job runs the same entry point. The command/settings contract check also verifies the installed command tree against the user documentation.

| README section / phase | Delivered behavior | Deterministic tests | Owning documentation |
| --- | --- | --- | --- |
| Requested feature scope | All six product areas composed in the existing bot | `test_commands.py`, all product suites | [Product policy](product.md), [commands](commands.md) |
| Match workflow / match foundation | Channel/thread challenges, explicit positions, negotiated revisions, identical confirmation | `test_arena.py`, `test_commands.py` | [Setup and negotiation](product.md#setup-and-negotiation) |
| Server setup and administration | Category/output routing, moderator roles, prefixes/names, presets, defaults, budgets, models and audit | `test_arena.py`, `test_settings.py`, `test_commands.py`, `test_preflight.py` | [Setup](product.md#setup-and-negotiation), [deployment](deployment.md) |
| Match channels, spectators, threads | Effective role denies, debater/staff allows, thread/reaction controls, origin links, preserved moves/closure | `test_discord_gateway.py`, `test_arena.py` | [Channels](product.md#channels-and-durable-lifecycle) |
| Per-match settings | Every toggle/parameter visible, validated and saved; disabled dependencies normalized; accepted rules locked | `test_settings.py`, `test_commands.py`, `test_arena.py` | [Every feature](product.md#every-match-feature) |
| Live moderation and claim tracking / argument assistance | Exact attributed quotes, stable revision IDs, kinds, relations, clarification, fallacy/coaching/civility controls | `test_assistance.py`, `test_providers.py` | [Research boundaries](product.md#research-and-model-boundaries) |
| Background research and fact checking | Real search and page fetch, provenance/dates, explicit sourced verdicts, disputes/rechecks/history, honest failure/budget states | `test_assistance.py`, `test_providers.py` | [Research](product.md#research-and-model-boundaries) |
| Response deadlines and endings / lifecycle | 24-hour designated-response clock, submit, requests, pause/resume/extensions, reminders, forfeit/concession/draw/cancel, outage recovery | `test_arena.py`, `test_worker.py`, `test_discord_gateway.py` | [Durable lifecycle](product.md#channels-and-durable-lifecycle) |
| LLM scoring, results, feedback / judging | Accepted weighted rubric, references, accuracy exclusions, ties/inconclusive, independent feedback and live/final separation | `test_competition.py`, `test_commands.py`, `test_assistance.py` | [Judging](product.md#judging-and-competition) |
| Leaderboards and competition | Ranked-v1 eligibility, snapshotted Elo policy, repeat/activity limits, filters, result links, chronological corrections | `test_competition.py`, `test_worker.py` | [Rating policy](product.md#judging-and-competition) |
| Argument training modes and behavior / training | Spot/selected/mixed/battle/repair/sound, explanation/alternative-label grading, variants, hints/difficulty, durable progress | `test_training_profiles.py`, `test_providers.py` | [Training](product.md#training-and-profiles), [commands](commands.md) |
| Fallacy reference | Original curriculum for ten families, per-entry Bo Bennett attribution and URLs, no bulk copying | `test_training_profiles.py`, `test_commands.py` | [Reference use](product.md#training-and-profiles) |
| User profiles and tendencies / profiles | Topic/assigned stance history, themes/approaches, evidence/sample counts, chronology, strengths/practice, consent/visibility/correction/removal | `test_training_profiles.py`, `test_assistance.py` | [Profiles](product.md#training-and-profiles) |
| Command surface | All README command families plus extension/request/review/retry/vote/answer/current/library controls | `test_commands.py`, `check-product-contract.py` | [Executable commands](commands.md) |
| Implementation phases | All six phase checkboxes completed in README | `check-product-contract.py`, all product suites | [README](../README.md), this checklist |
| Development validation | Foundation upgrades, rollback, backups, fatal supervision, real container persistence, Terraform fmt/validate/mocked plans | `test_storage.py`, `test_runtime.py`, `test_worker.py`, `check-container.py`, Terraform tests | [Architecture](architecture.md), [development](development.md), [recovery](deployment.md) |

## Settings acceptance matrix

The parameter table in [product policy](product.md#every-match-feature) is authoritative for starting values and ranges. `test_settings.py` exercises every switch and rejects invalid types/dependencies. The following tests exercise effects beyond serialization.

| Settings | Behavioral coverage |
| --- | --- |
| `claims`, `research`, `corrections`, `on_demand` | `test_assistance.py`: hidden internal extraction, independent on-demand, sourced flags, delayed/immediate delivery, budgets and histories |
| `fallacies`, `coaching`, `civility`, `live_scores` | `test_assistance.py`: passage grounding, frequency, graph links, private delivery, staff review events and provisional scores |
| `judging`, `feedback`, `ranked` | `test_competition.py`, `test_commands.py`: rubric/weights/references, ties/inconclusive, independent/private feedback, immutable ranked preset and Elo |
| `turns`, `inactivity`, `reminders`, `limits` | `test_arena.py`, `test_worker.py`: qualifying responses, explicit flexible requests, submit, saved clocks, once-only reminders/closures and caps |
| `reactions`, `threads`, `archive` | `test_discord_gateway.py`: effective permissions and closure policy across moves; `test_arena.py`: thread input exclusion and movement-off policy |
| `audience` | `test_arena.py`: eligibility, separate vote count and unchanged official result |
| `profiles` | `test_training_profiles.py`: dual consent, private reads, timestamp eligibility, sample display, correction/exclusion and deletion tombstones |

## Failure and persistence matrix

| Failure boundary | Coverage |
| --- | --- |
| Wrong guild, spectator mutation, staff/Admin mismatch, private reads | `test_arena.py`, `test_commands.py`, `test_training_profiles.py` |
| Duplicate events, competing accept/end actions, late edits during judging | `test_arena.py`, `test_competition.py`, `test_worker.py` |
| Restarts, expired leases, retries, delivery acknowledgement crashes | `test_worker.py`, `test_discord_gateway.py`, `test_storage.py` |
| Disconnected/unobserved clocks and failed history reconciliation | `test_arena.py`, `test_worker.py`, `test_discord_gateway.py` |
| Missing keys, invalid JSON, fabricated quotes/references, unsupported pages, DNS/URL restrictions | `test_providers.py`, `test_assistance.py`, `test_worker.py` |
| Research/LLM budgets and pending evidence dependencies | `test_assistance.py`, `test_worker.py`, `test_commands.py` |
| Opt-out, removed insights, changed transcript and old-job regeneration | `test_training_profiles.py`, `test_competition.py` |
