# Architecture and validation

The runtime is one Python asyncio process using discord.py and aiohttp. SQLite stores matches, messages, claims and their revisions, audit events, results, ratings, user preferences, training sessions, durable jobs and delivery state. Records are JSON documents within a transactional table; SQLite WAL and full synchronization preserve committed writes. `Store.atomic()` supports nested transactions. The image contains no credentials.

| Module | Responsibility |
| --- | --- |
| `core.py` | Match rules, mutual consent, turns, clocks, results and replayable Elo |
| `store.py` | Transactional persistence and online backups |
| `bot.py` | Discord commands, persistent buttons, permissions, delivery/recovery and background work |
| `intelligence.py` | Analysis, research, budgets and validated structured judging |
| `providers.py` | Bounded provider HTTP and public evidence retrieval |
| `training.py`, `fallacies.json` | Original exercises, grading, battles and practice history |
| `profiles.py` | Consent, evidence-linked profiles, corrections and removal |
| `config.py` | Environment configuration |

The domain engine contains no Discord calls. The adapter performs permission checks, records accepted state, and reconciles external Discord operations. A deterministic channel topic identifies channel creation that succeeded before a process crash. Persisted jobs resume after restarts. Delivery to external Discord APIs is at least once; a crash immediately after a successful send can duplicate a notification. Match results and rating updates are transactional and idempotent.

Official transcripts include only the two participants' text in the main match channel. Discussion-thread messages and reactions are excluded. Message edits and deletions invalidate prior claim checks. LLM results are validated before storage: quoted claims must occur in the original message, source quotations must occur in inspected pages, and judging references must identify official messages. Scores and winners are computed from the agreed rubric rather than trusting a model-supplied winner.

Training puzzles in `fallacies.json` are original examples with links crediting Logically Fallacious reference entries. Live grading checks reasoning separately from identification; a correct label alone does not establish mastery. Practice is separate from ranked human matches. Missing provider configuration produces an explicit unavailable assessment.

## Development checks

Use Python 3.12, install `requirements-dev.txt`, and run `bash scripts/validate.sh`. The same entry point runs in the required `Clusterfork validation` CI job. It checks Markdown, Python lint, deterministic unit/integration tests, infrastructure policy invariants, and Python compilation. The runtime dependencies and their transitive versions are pinned in `requirements.txt`.

For infrastructure changes also run:

```bash
terraform -chdir=infra init -backend=false
terraform -chdir=infra fmt -check
terraform -chdir=infra validate
```

Tests substitute provider transports and Discord objects. They do not send Discord messages, spend API credits, publish images or mutate a cluster. A real rollout and test-server smoke check are still required to verify permissions, enabled gateway intents, registry access, local-volume provisioning and provider account behavior. The [deployment guide](deployment.md) explains those operator steps.
