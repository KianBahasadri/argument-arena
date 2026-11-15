# Commands and interaction states

Use these commands in the configured server, including discussion threads. Responses and menus are ephemeral: only the invoking member sees them. Menus belong to that member and server, expire after 15 minutes, and can be reopened with the same command. Routine actions use selectors, buttons and text forms. Match IDs and configuration JSON are not required.

| Command | Inputs and authority | Opens |
| --- | --- | --- |
| `/challenge` | Human member; required `member` only. Example: `/challenge @member` | Private topic/position form, presets, feature controls and review before Send challenge |
| `/match` | Members; no arguments | Current debate in a match channel or its discussion thread; otherwise a paged match selector |
| `/train` | Members; no arguments; sessions are private to their owner | Practice modes, selected fallacies, difficulty/topic, answers, hints, progress and retry |
| `/profile` | Members; no arguments | Member picker, permitted insights, public match history and owner-only consent/correction/removal controls |
| `/leaderboard` | Members; no arguments | Competitive standings with a filter form for topic, days, format and minimum matches |
| `/admin` | Administrator or configured moderator; no arguments | Authorized setup, diagnostics, policy/audit or match moderation |
| `/help` | Members; no arguments | Match quick start and a menu of detailed feature guidance |

## Challenge and negotiation

1. Run `/challenge @member` in a server channel or discussion thread. Fill in a topic (3–500 characters), your position and the opponent's position (1–500 characters each).
2. Review the private summary. A preset replaces feature settings; the initial selection uses configured server defaults. Features and parameters exposes all 20 switches and their parameters through typed controls. Edit topic and positions returns to the form.
3. Choose Send challenge when ready. Cancel setup or abandon it to leave no challenge or active channel. Unsent setup expires after 15 minutes or a process restart. The originating channel/thread link is retained when sent.
4. Both participants open `/match` and select the pending challenge. Either may propose new topic/positions, choose a preset, edit features or decline. Every change increments the revision and clears both confirmations.
5. Each participant chooses Confirm reviewed revision. Both must confirm the same revision; stale panels cannot accept changed rules. Only then does the durable worker create the debate channel. Pending sent challenges expire after seven days.

Features explains dependencies: research off disables factual corrections; judging off disables ranked play; ranked-v1 applies its shared judging/coaching/live-score/turn/deadline/limit rules. Reminder lead time must be shorter than the response window. Parameter forms accept numbers, text or one item per line; booleans, enumerated choices, first speaker and the single operator Go model use menus. All six rubric weights are submitted together as space-separated integers totaling 100. Full feature details exposes unabridged parameters. Accepted rules are locked.

## Match controls

The match selector offers My matches / All server matches, topic search and pagination. The menu shows only actions allowed by the current state and authority. Permissions and state are checked again when used. Other members open their own private menu to review and respond.

| Menu action | Authority and behavior |
| --- | --- |
| Status | State, required speaker, exact UTC deadline, saved remaining seconds, proposals and pending/failed jobs |
| Features | Members may inspect every setting; only participants may edit before acceptance |
| Edit topic and positions / Choose a preset / Confirm reviewed revision / Decline challenge | Participants, pending challenge only; both confirmations are reset by edits |
| Submit turn | Required participant in an active submit-mode match, after posting a new official message |
| Claims and evidence | Public ledger must be enabled; choose an attributed quote to read research/correction history |
| Fact-check this claim | Participant; factual, non-stale claim and on-demand checks enabled; usage limits still apply |
| Dispute this claim / Link a related objection / Dispute result | Participant; reason form and optional HTTPS source; related claims are selected from the same match |
| Propose pause / Propose resume | Participant agreement or immediate audited staff action; save/restore remaining response time |
| Extend deadline | Propose 1–168 extra hours; opponent must agree, or staff applies immediately |
| Request a speaker | Flexible order only; select a participant and obtain peer agreement, or staff designates one |
| Agree to pending proposal | Opponent accepts the exact action and terms shown; stale proposals are rejected |
| Concede now | Immediate participant loss after an explicit confirmation; no peer agreement |
| Propose finish | Mutual ending and enabled final judging; without judging, an inconclusive result |
| Propose draw | Mutual ending recorded as a draw |
| Propose cancellation | Mutual cancellation; staff may cancel immediately; not a concession |
| Results | Recorded outcome, rubric/report/references, rating changes and feedback allowed for this viewer |
| Audience vote | Eligible human during an enabled post-match voting window; participant selected through a menu; separate from ratings/judging |
| Moderation | Staff-only Audit, Retry failed work, Archive, Correct result or Close with staff decision |

Agreed round/message limits automatically finish the match. A round is two completed turns. The default inactivity window is **24 hours after a member is explicitly designated the next required speaker**. Alternating turns designate one at start and after each completed turn; flexible order requires an agreed speaker request or staff designation. Only a qualifying response clears that clock. Missing an enabled deadline causes forfeiture; edits, reactions and discussion messages do not reset it. Pauses freeze remaining time. The accepted window can be different or disabled.

Finish, draw and cancellation require agreement from ordinary participants. Staff lifecycle interventions are immediate and audited. Concession always belongs to a participant. A judging failure remains pending/unavailable until resolved; it never invents a loss.

## Training, profiles and administration

`/train` groups Start practice (spot, selected, mixed, battle, repair or sound), difficulty/topic forms, Current exercise, Answer exercise, Request a hint, Progress, Fallacy library, Stop session and Retry failed grading. One active session belongs to each member. Answers remain durable while grading is pending. Selected-fallacy practice is reached through the library. Original exercises link to attributed references and never change competitive ratings.

`/profile` opens your panel and a member picker. View profile checks visibility on every read, including staff reads. Public match history is separate from generated insights and has topic/period filters. Your panel includes Privacy and consent, Correct or exclude an insight, and Remove generated insights with confirmation. Defaults remain analysis off, private visibility and no training sharing. Correction uses a match selector and note form. Public history remains accessible without revealing private insights.

`/admin` checks Administrator or configured moderator authority at execution. Moderators can choose matches and use audited lifecycle/result controls, failed-job retry and completed-match archival. Closure/correction uses outcome and winner menus plus a required explanation form. Administrators also have Set up routes (three category pickers: Active, Completed and Cancelled), Output channels and moderator roles, Default match features, View server configuration, Server audit history and Connection diagnostic. Categories are Discord folders; the setup panel explains each destination. Completed includes concessions and forfeits, and the same category can serve multiple routes. Older saved policies with a separate forfeited category remain readable; that legacy destination is ignored. Ordinary server setup needs no JSON. Advanced server policy retains a documented JSON patch form for unusual policy/preset changes. Anyone may inspect server configuration from `/help` → Server rules → View server configuration.

Errors explain the condition and the next step: which command or menu to reopen, who has authority to fix it, and any relevant limits. Cooldown errors include the remaining wait. Match Status and training's Current exercise translate background failure codes into causes and retry instructions; daily usage limits reset at midnight UTC, while per-match limits do not. Known Discord permission or missing-item failures identify what an administrator should check. Unexpected failures provide an opaque reference that the operator can match to the sanitized logs. Error responses stay private and do not include exception bodies, credentials or private provider responses. An unexpected failure may happen after an action was saved, so the message asks members to check current status before retrying.

DMs, other guilds, another member's components, bot/self challenges, unauthorized mutations and invalid transitions are rejected. Provider failures remain explicit states. Private DM delivery failures never fall back to public coaching. See [product policy](product.md) for full defaults, outcome semantics and privacy boundaries.

## Before and after inventory

The former surface had **43 executable slash-command actions** across seven roots: 25 match actions, nine training actions, four profile actions, two server-settings actions, plus setup, diagnostic and leaderboard. It now has **seven executable commands**, each a single entry point with no visible subcommands.

| Former area | Former actions | Current location |
| --- | --- | --- |
| Match creation and acceptance | challenge, accept, decline, settings | `/challenge` draft and `/match` negotiation |
| Match management | status, submit, claims, check, dispute, pause, resume, extend, request, concede, draw, finish, cancel, result, vote | `/match` state-aware menu and claim selector |
| Match staff/history | archive, correct, audit, retry, close, history | `/match` → Moderation or `/admin`; history in `/profile` |
| Training | start, fallacy, hint, answer, current, progress, library, stop, retry | `/train` menus and forms |
| Profiles | view, settings, remove-insights, correct | `/profile` and member picker |
| Server setup and policy | setup, diagnostic, settings server, settings audit | `/admin`; public configuration from `/help` |
| Competition | leaderboard | `/leaderboard` and Filter standings |
| Guidance | README required | `/help` quick start and topic menu |

Guild command synchronization replaces the old registrations on deployment. Existing matches, sessions, outcomes, privacy preferences and settings remain in the same database; no schema migration is required. Member panels are intentionally reopened after a bot restart.
