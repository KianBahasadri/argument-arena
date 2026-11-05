# Argument Arena

A Discord bot for a server built around arguments: organize one-on-one debate matches, moderate the conversation, research claims, score arguments with LLMs, and help members improve through feedback and practice.

**Status: feature proposal.** This repository currently contains the product plan. The bot, commands, integrations, and features below are proposed and have not been implemented. Command names, defaults, rating rules, and implementation phases are initial design suggestions.

## Requested feature scope

- Give the bot Administrator permissions so it can manage the server's debate workflow.
- Let two members start and manage an argument using bot commands.
- Create a public match channel where only the two participants can post, alongside the bot's moderation messages.
- Let everyone watch, add emoji reactions, and create and participate in discussion threads.
- Let informal arguments in those threads become their own official matches through the same commands.
- Use LLMs to moderate, identify each participant's claims, score arguments, and give feedback.
- Research claims in the background and flag incorrect factual statements with evidence.
- Let participants turn optional features on or off for each match when setting it up.
- End a match with a loss when someone fails to respond within the agreed deadline, with one day as the initial default.
- Maintain leaderboards and match results.
- Provide chess-style argument training, including battles against a bot that deliberately makes logical fallacies.
- Offer practice for particular fallacies, using Logically Fallacious as the reference library.
- Move finished match channels into the appropriate server categories automatically.
- Build user profiles covering positions argued for or against, interests, and patterns in argument style, including moral versus empirical themes and technology or engineering versus art.

The sections below expand those requests into proposed behavior. Additional controls, command names, and defaults are suggestions for implementation rather than settled requirements.

## Match workflow

1. A member challenges another member with a topic and proposed positions, either in a normal server channel or in a discussion thread.
2. The bot presents the match settings, including optional fact checking, assistance, judging, response deadlines, and ranked status.
3. The opponent accepts, declines, or proposes changes. Both participants confirm the same settings before the match begins.
4. The bot creates a channel under the configured active-matches category and posts the topic, participants, positions, rules, enabled features, and response deadline.
5. The participants argue. The audience watches, reacts, and uses public threads for side conversations. Enabled LLM features identify claims, research evidence, moderate, and provide updates.
6. The match ends through an agreed finish, concession, completed rounds, inactivity forfeit, or moderator intervention.
7. The bot publishes the result and any enabled judging report, updates eligible records and leaderboards, and generates enabled profile insights.
8. If automatic archival is enabled, the bot moves the channel to the configured completed, forfeited, or cancelled category and applies the agreed archive policy.

Participants can start a new match from any side discussion without ending or changing the original match. The new channel links back to its originating thread.

## Server setup and administration

- Administrator-based installation for the intended server, with command access restricted by role and action.
- A setup command to choose active, completed, forfeited, and cancelled match categories; announcement and results channels; and moderator roles.
- Configurable channel names, match IDs, category routing, and archive behavior.
- Server defaults and reusable match presets, such as casual, ranked, fact checking off, or coaching on.
- Staff controls to pause, resume, cancel, close, or review a match and correct a recorded result.
- A record of accepted settings, match events, moderator changes, and rating corrections.
- Limits on concurrent matches, challenge frequency, research usage, and LLM spending, with clear status when a limit is reached.
- Configurable LLM provider and model for moderation, judging, training, and research summaries; provider choice remains open.

Server permissions, staff authority, service credentials, and server rules are administration settings. They are separate from optional match features that participants can toggle.

## Match channels, spectators, and threads

| Action | Two debaters | Other server members | Bot and authorized staff |
| --- | --- | --- | --- |
| Read the main match channel | Yes | Yes | Yes |
| Send ordinary messages in the main channel | Yes while active | No | Yes for moderation and bot output |
| Add emoji reactions | Yes when enabled | Yes when enabled | Yes |
| Create public discussion threads | Yes when enabled | Yes when enabled | Yes |
| Send messages in discussion threads | Yes when enabled | Yes when enabled | Yes |
| Issue a challenge from a thread | Yes | Yes | Subject to command permissions |
| Change another match's settings or result | No | No | Authorized staff only |

- Spectator conversation stays in threads so it does not interrupt the main argument.
- Thread messages and emoji reactions do not enter the official debate transcript or LLM score. An optional audience vote is displayed separately.
- Starting a match from a thread carries over the chosen topic and a conversation link. Existing thread participants do not automatically become contestants.
- Closing a match locks ordinary main-channel posting. Whether discussion threads remain open follows the configured archive policy.
- Moving a channel between categories must preserve its intended audience and posting permissions.

Discord documents separate permissions for parent-channel messages and messages in threads. The implementation should use channel overwrites and thread permissions to support this layout. Server owners and members with Administrator permission retain Discord's built-in ability to bypass channel overwrites. See [Discord permissions](https://docs.discord.com/developers/topics/permissions) and [Discord threads](https://docs.discord.com/developers/topics/threads).

## Per-match settings

Every optional per-match feature must expose an explicit on/off control during setup. Features with parameters also expose those parameters. The bot shows the effective settings before acceptance and saves that configuration with the match.

These are suggested starting defaults, not final policy:

| Feature | On/off behavior | Additional settings | Suggested default |
| --- | --- | --- | --- |
| Public claim tracking | Publish attributed claims and their status | Update frequency and detail | On |
| Background fact checking | Research factual claims as the match progresses | Research depth, source preferences, budget | On |
| Automatic factual corrections | Post evidence-based flags for incorrect claims | Confidence threshold and immediate versus batched delivery | On when research is enabled |
| On-demand fact checks | Let participants request research for a specific claim | Request limit and research depth | On |
| Live fallacy detection | Flag possible reasoning errors with explanations | Fallacy families and notification frequency | Off |
| Live coaching | Offer argument improvement suggestions during the match | Delivery location and frequency | Off |
| Civility feedback | Post reminders about tone and personal attacks | Strictness and escalation behavior within server rules | On |
| Live scores | Display provisional scores during the debate | Update interval | Off |
| Final LLM judging | Score the completed argument and propose a result | Rubric, weights, judge model, tie policy | On |
| Post-match feedback | Give each participant a review and practice suggestions | Detail level and public or private delivery | On |
| Turn enforcement | Require a designated next speaker | First speaker and turn structure | On |
| Inactivity forfeits | End the match when the required response is overdue | Response window | On; 24 hours |
| Deadline reminders | Notify the member whose response is due | Timing and notification destination | On |
| Round, message, or length limits | End or constrain the debate using agreed limits | Number of rounds and permitted length | Off |
| Spectator reactions | Allow audience emoji reactions | Any server-defined reaction restrictions | On |
| Public discussion threads | Allow side conversations during the match | Thread creation and post-match closure policy | On |
| Audience voting | Collect a separate audience verdict | Voting window and eligibility | Off |
| Ranked participation | Apply the result to competitive ratings | Eligible rating preset | Off |
| Profile insights | Use this match for topic, stance, and argument-style analysis | Each participant's profile preferences | On only for users who opt in |
| Automatic archival | Move and lock the match channel when it ends | Destination category and thread policy | On |

Configuration must explain dependencies. Automatic factual corrections require background research; disabling research disables those corrections. Turning off the public claim ledger does not prevent internal claim extraction needed for enabled research. On-demand checking can remain available independently of automatic research. Turning off judging makes the match unranked under the proposed ranked preset.

Topic, participants, and stated positions are also chosen during setup. Participants cannot change competitive rules unilaterally after acceptance; agreed changes or moderator interventions are recorded. Server rules continue to apply when match-level civility feedback is off.

## Live moderation and claim tracking

- Recognize substantive claims in each debater's messages and state who made them: for example, "Claim C12, made by @member: ...".
- Give each claim an ID, author, original message link, timestamp, original wording, and clearly labelled summary.
- Distinguish empirical claims, value judgments, opinions, definitions, predictions, and questions so research is applied appropriately.
- Link claims to supporting evidence, counterclaims, responses, concessions, revisions, and unresolved objections.
- Track whether a participant has answered a major point without treating every missing reply as a factual concession.
- Ask for clarification when a claim or definition is ambiguous rather than inventing a stronger or weaker version of it.
- Identify possible fallacies, contradictions, unsupported assertions, and topic drift when the corresponding assistance is enabled.
- Explain a possible fallacy using the relevant passage and reasoning. A fallacy label alone is insufficient feedback.
- Apply the same agreed rules to both participants and keep LLM analysis distinguishable from staff actions.
- Batch or summarize bot updates so moderation does not overwhelm the argument.

## Background research and fact checking

- Queue checkable factual claims for research while participants continue arguing.
- Search for evidence and inspect retrieved sources; an LLM's recollection alone is insufficient for a factual correction.
- Prefer relevant primary sources where available and consider publication dates, context, source quality, and contrary evidence.
- Attach the supporting URLs, source titles, research timestamp, and a concise explanation to each completed check.
- Use explicit outcomes such as **supported**, **contradicted**, **partly supported**, **disputed**, **insufficient evidence**, and **not fact-checkable**.
- When evidence warrants it, clearly tell the author that a claim is incorrect and explain what the evidence supports instead.
- Keep moral preferences and subjective judgments separate from checkable factual premises within the same argument.
- Let participants submit sources, challenge an interpretation, request a recheck, or point out that the extracted claim misrepresented their message.
- Revise a check when better evidence appears and retain a visible correction history.
- Account for edited or deleted messages so an old verdict is not silently attached to changed wording.
- Show pending, failed, or budget-limited research as such. Missing research is not evidence that a claim is false.
- Treat messages and retrieved pages as material to analyze, keeping their instructions separate from the bot's rules and tool permissions.

Live fact checking, automatic public flags, and on-demand checking follow the accepted match settings. Research results used in judging must be traceable to the same match evidence.

## Response deadlines and match endings

- The initial proposed response window is **24 hours** after a participant is explicitly marked as the next required speaker.
- Show the member who owes a response and the exact deadline in the match status.
- In turn-based matches, accept a submitted turn or qualifying response from that member to advance the turn and start the opponent's clock.
- Bot messages, spectator activity, reactions, and the other participant posting again do not reset the required speaker's deadline.
- If flexible turn order is enabled, the match still needs an explicit response request before an inactivity forfeit can apply.
- Send configurable reminders before expiry.
- When the deadline passes, announce the missing response, mark that member as losing by inactivity forfeit, record the result, and close the match once.
- Let members concede, propose a draw, or mutually agree to finish. Staff can cancel an invalid match or resolve a dispute.
- Support pauses or extensions by mutual agreement or staff action, showing the revised deadline. Service interruptions must be accounted for before assigning an automatic loss.
- Distinguish a judged win, agreed draw, concession, inactivity forfeit, and cancellation in results and statistics.
- A forfeit records the procedural outcome; it does not establish that the opponent's factual claims are correct.

If automatic archival is enabled, the bot moves the channel to the destination for that outcome, posts the final summary, and applies the closure policy. If it is disabled, the match still ends and its result is recorded; the channel stays in place for staff to organize.

## LLM scoring, results, and feedback

- Judge the two participants' official match messages using the rubric agreed before the match.
- Score dimensions such as reasoning, evidence quality, factual accuracy where assessed, engagement with objections, clarity, and adherence to the agreed debate rules.
- Publish the scoring breakdown, weights, supporting message and claim references, and explanation for the result.
- For value-based debates, assess consistency and justification without assigning a factual truth score to a moral preference.
- Distinguish winning the debate under its rules from proving an entire worldview or topic true.
- Support a draw or an inconclusive result when the rubric or evidence does not justify a winner.
- Give each participant specific strengths, weak points, unanswered objections, and examples of how to improve.
- Link recurring reasoning issues to relevant training exercises.
- Keep final judging separate from live scores, audience sentiment, and timeout outcomes.
- Allow a disputed judgment to be reviewed by staff. An amended result must update the record and any affected ratings.

The initial scoring scale, weights, tie thresholds, and review process remain open implementation choices.

## Leaderboards and competitive records

- Server leaderboards for eligible ranked matches.
- User records showing wins, losses, draws, forfeits, and match history.
- Competitive ratings, with Elo or another rating system to be selected before implementation.
- Filters for time period, topic, and agreed match format where there is enough activity.
- Links from results and ratings to the underlying match and judging report.
- Separate casual matches and training progress from competitive ratings.
- Use a shared ranked preset so members cannot disable required judging rules while retaining ranked status.
- Show rating changes and the reason for each update, including reversals after a corrected result.
- Treat emoji counts and any audience vote as separate social feedback rather than the official competitive score.

The proposed ranked preset requires final judging and consistent scoring rules. Its exact rating formula, minimum activity, treatment of forfeits, and repeat-opponent rules remain to be decided.

## Argument training

Training should feel like chess training: short drills, focused practice, explanations after an attempt, and progression based on demonstrated skill.

### Training modes

- **Spot the fallacy:** the bot deliberately makes a flawed argument; the member identifies the fallacy, quotes the relevant part, and explains the reasoning error.
- **Practice a chosen fallacy:** select a particular fallacy or family and receive varied exercises targeting it.
- **Mixed puzzles:** encounter a mix of fallacies without being told the category in advance.
- **Training battles:** debate the bot across several turns while it introduces deliberate reasoning errors for the member to challenge.
- **Repair the argument:** rewrite a flawed argument to remove the error while preserving its intended point where possible.
- **Sound or fallacious:** include valid arguments so practice rewards reasoning rather than guessing that every example contains a fallacy.
- **Personalized review:** revisit issues identified in the member's matches when they enable training recommendations.

### Training behavior

- Accept free-text explanations and reasonable alternative fallacy labels when the reasoning is correct.
- Grade identification and explanation separately; naming a fallacy without showing the error is not a complete solution.
- Offer optional hints, adjustable difficulty, topic selection, and explanations after answering.
- Track accuracy, recurring mistakes, progress by fallacy, and recommended next exercises.
- Keep training sessions separate from human-versus-human ranked results and from assumptions about the user's beliefs.
- Link each reference-based exercise to its source entry and use original practice scenarios and explanations.

### Fallacy reference: Logically Fallacious

Use the [Logically Fallacious fallacy library](https://www.logicallyfallacious.com/fallacies) as the requested reference for fallacy names, descriptions, and further reading. The site accompanies Bo Bennett's book; exercise references should credit the relevant page and preserve its URL.

Initial practice topics can include:

| Fallacy | Reference |
| --- | --- |
| Ad hominem | [Ad Hominem (Abusive)](https://www.logicallyfallacious.com/logicalfallacies/Ad-Hominem-Abusive) |
| Straw man | [Strawman Fallacy](https://www.logicallyfallacious.com/logicalfallacies/Strawman-Fallacy) |
| False dilemma | [False Dilemma](https://www.logicallyfallacious.com/logicalfallacies/False-Dilemma) |
| Begging the question | [Begging the Question](https://www.logicallyfallacious.com/logicalfallacies/Begging-the-Question) |
| Hasty generalization | [Hasty Generalization](https://www.logicallyfallacious.com/logicalfallacies/Hasty-Generalization) |
| Slippery slope | [Slippery Slope](https://www.logicallyfallacious.com/logicalfallacies/Slippery-Slope) |
| Cherry picking | [Cherry Picking](https://www.logicallyfallacious.com/logicalfallacies/Cherry-Picking) |
| Shifting the burden of proof | [Shifting of the Burden of Proof](https://www.logicallyfallacious.com/logicalfallacies/Shifting-of-the-Burden-of-Proof) |

The initial list is a starting set; practice should expand to additional entries in the library. The library is a reference for curriculum design, not an implemented integration in this repository.

## User profiles and argument tendencies

Profiles combine a debate record with optional, evidence-linked analysis of how a member argues in the server.

- **Positions argued:** propositions the user has supported or opposed, with match links and time context.
- **Interests:** recurring topics such as ethics, politics, technology, engineering, science, art, or culture.
- **Argument themes:** how often the user engages in moral or value-based discussion, empirical claims, conceptual reasoning, or mixed arguments.
- **Approach:** tendencies such as citing evidence, using examples, discussing definitions, appealing to principles, or focusing on practical consequences.
- **Strengths and practice needs:** recurring patterns in clarity, responding to objections, evidence use, and possible reasoning errors.
- **Change over time:** improvements and changes in argued positions, rather than a permanent label based on early matches.
- **Competitive and training history:** eligible results, scores, progress, and suggested exercises.

Example profile observations:

- "Often debates moral questions and justifies positions through general principles."
- "Most recent matches concern technology and engineering, with fewer discussions about art."
- "Frequently uses empirical evidence; several recent claims were independently supported."
- "Has argued both sides of this proposition in practice, so these matches do not establish a personal stance."

Descriptions must show their evidence and sample size and distinguish observed argument behavior from a psychological diagnosis. Arguing a side in training, roleplay, or an assigned-position match does not establish that the user personally believes it.

Users can view the evidence behind a profile observation, correct a mischaracterization, choose visibility, disable future tendency analysis, and request removal of generated insights. Profile analysis uses eligible bot-managed matches and opted-in training; it does not assume permission to analyze unrelated server conversations. Match-level profile settings and each user's preferences both apply.

## Proposed command surface

All commands below are illustrative. Buttons, select menus, and forms can handle settings that would be cumbersome as slash-command arguments.

| Command | Purpose |
| --- | --- |
| `/setup` | Configure categories, server defaults, and moderator roles |
| `/settings server` | View or change server-level configuration |
| `/match challenge @member topic:<topic>` | Propose a match from a channel or thread |
| `/match accept <id>` / `/match decline <id>` | Respond to a challenge |
| `/match settings <id>` | Review or propose changes to the match configuration |
| `/match status <id>` | Show participants, rules, next speaker, and deadline |
| `/match submit` | Submit a completed turn when turn-based play is enabled |
| `/match claims` | View claims, responses, and research status |
| `/match check <claim-id>` | Request an enabled on-demand fact check |
| `/match dispute <claim-or-result-id>` | Challenge an extraction, fact check, or judgment |
| `/match pause` / `/match resume` | Request an agreed pause or resume play |
| `/match concede` | Concede the match |
| `/match draw` | Propose an agreed draw |
| `/match finish` | Propose ending the argument and starting enabled final judging |
| `/match cancel <id>` | Cancel through the allowed participant or staff workflow |
| `/match result <id>` | Retrieve a completed result and feedback |
| `/match archive <id>` | Let authorized staff archive a finished channel manually |
| `/leaderboard` | View competitive standings and filters |
| `/profile [@member]` | View an available debate profile and history |
| `/profile settings` | Manage profile analysis and visibility preferences |
| `/profile remove-insights` | Request removal of generated tendency analysis |
| `/train start` | Start a puzzle or training battle |
| `/train fallacy <name>` | Practice a selected fallacy |
| `/train hint` | Request a hint in the current exercise |
| `/train progress` | View training results and suggested practice |

Read-only spectators should still be able to invoke permitted application commands, including issuing a new challenge. Interaction responses and settings forms must respect the main-channel conversation rules.

## Proposed implementation phases

- [ ] **Match foundation:** administrator setup, challenges, mutual acceptance, settings, channel permissions, reactions, public threads, and challenges originating in threads.
- [ ] **Lifecycle:** turn tracking, 24-hour response deadlines, reminders, concessions, draws, forfeits, moderator controls, durable results, and category archival.
- [ ] **Argument assistance:** claim attribution, background research, evidence-linked corrections, configurable moderation, and dispute handling.
- [ ] **Judging and competition:** final scoring, post-match feedback, ranked presets, records, ratings, and leaderboards.
- [ ] **Training:** Logically Fallacious references, focused drills, mixed puzzles, bot battles, explanations, and progress tracking.
- [ ] **Profiles:** topic interests, positions argued, argument tendencies, evidence links, user controls, and personalized practice recommendations.

Implementation will use Python with discord.py, hosted on the owner's server. Infrastructure and deployment will be defined as code using Terraform and appropriate host configuration tools. The bot and its infrastructure have not been implemented. Database, LLM provider, and research provider choices remain open.

## Development validation

With Python 3.12, install the pinned validation dependencies and run the shared validation entry point:

```bash
python3 -m pip install --requirement requirements-dev.txt
bash scripts/validate.sh
```

Validation currently checks all repository Markdown because the repository contains only the feature proposal. When adding the bot or infrastructure, extend `scripts/validate.sh` and its dependency setup with the relevant application tests, lint, build, and infrastructure checks. Keep this entry point and the required `Clusterfork validation` CI check aligned so remote development validates the code it changes.
