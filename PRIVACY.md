# Argument Arena Privacy Policy

Effective date: November 14, 2026

Argument Arena is a Discord bot for organized debates, research, judging, reasoning practice and optional user profiles. This policy describes the official bot operated by the maintainer of [KianBahasadri/argument-arena](https://github.com/KianBahasadri/argument-arena) ("we", "us" or the "operator"). Independently hosted copies have their own operators and must provide their own privacy information.

## Contact and requests

For privacy questions, access, corrections or deletion, contact the owner or an administrator of the Discord server where you use Argument Arena and ask them to reach the bot operator. If you cannot reach them, [open a GitHub issue](https://github.com/KianBahasadri/argument-arena/issues/new) asking the maintainer for a private contact method. GitHub issues are public: include only what is needed to establish contact, and send personal data through the private channel arranged with the operator.

Provide your Discord user ID, the relevant server and the scope of your request privately. We may verify that you control the account. We will address verified requests promptly and within any applicable legal deadline. You do not need to enable profile analysis to make a request.

## Information the bot processes

Depending on the features you use, the bot processes:

- Discord user, server, channel, role and message IDs; permission information; message links and timestamps needed to authorize commands and operate matches.
- Challenges, topics, assigned positions, accepted settings, match events, official participant messages, message revisions and deletion markers.
- Extracted claims, summaries, evidence links, retrieved source text and metadata, research disputes, AI feedback, judging reports, results, ratings and optional audience votes.
- Training topics, exercises, submitted answers, grades, hints, progress and recommendations.
- Profile consent and visibility settings, optional evidence-linked observations, corrections, exclusions and removal records.
- Operational information such as request counts, queued jobs, delivery acknowledgements, health status and error types; information you voluntarily provide when asking for support.

Official transcripts include accepted participant text in managed match channels. Unrelated server conversations, spectator thread messages and reactions are not added to those transcripts or used for profile analysis. Audience votes, when enabled, are stored separately. The bot does not record voice or video or download ordinary Discord attachments as transcript content. It can retrieve public evidence URLs submitted through its research features.

Discord delivers the events needed to run the bot; receiving an event does not mean the bot saves it. The bot does not request your Discord password or collect payment details, advertising identifiers or your device IP address directly.

## Why we use information

We use information to operate negotiated matches, enforce accepted turns and deadlines, recover after interruptions, research claims, provide enabled assistance, record community results, offer training, respect profile preferences, resolve disputes, respond to requests and protect the service from abuse. Optional profile analysis is off by default and requires your opt-in as well as the match's profile setting.

Where a legal basis is required, we rely on providing the service you request, legitimate interests in operating a reliable and fair community service, consent for optional profile analysis, or compliance with legal obligations, as applicable. You may withdraw optional profile consent without ending ordinary match participation.

We do not sell personal information, share it for advertising, or use Discord message content to train or fine-tune AI models. "Training" in the bot means reasoning exercises for people, not training a machine-learning model.

## Who can receive information

**Other Discord members.** Match channels, published results, leaderboards and enabled public assistance are visible according to the server's permissions. Assigned positions describe what a participant argued, not necessarily their beliefs. Spectators or other members may copy information they can view.

**Private features and administrators.** Slash-command responses and training are normally visible only to the requesting member. Configured private coaching or feedback is sent by direct message. Profiles default to private; choosing public visibility makes them accessible to other members through the bot. Enabling training inclusion can add practice history to a profile. Application-level privacy controls do not prevent the bot operator or authorized infrastructure administrators from accessing the underlying database when needed for support, maintenance or requests.

**AI providers.** Enabled analysis, research summaries, judging and training grading can send relevant message text, transcript context, topics, positions, claims, source excerpts, answers and Discord identifiers or links to the operator's configured AI provider. The integration uses OpenCode Go, which routes requests to the selected model provider. The operator must select models whose processing terms are consistent with this policy, including the restriction on using Discord content for model training. Profile analysis being off does not turn off separately enabled match assistance or training grading.

**Search providers and source websites.** Research sends queries derived from claims to Brave Search API and retrieves public source URLs. A query or URL may contain information included in a claim or submitted link. Source websites receive ordinary request information, including the requested URL and the bot server's IP address.

**Service providers and legal obligations.** Hosting, backup and security providers may process data on the operator's behalf. We may also disclose information where required by law, consistent with Discord's rules and applicable law. Providers must be used under arrangements consistent with those rules, including restrictions on secondary use of Discord data.

Provider retention and processing depend on the selected service and account configuration; there is no promise of zero retention. See [OpenCode Go's model-specific processing information](https://opencode.ai/docs/console/go/#privacy), [OpenAI's business-data information](https://openai.com/enterprise-privacy/), [Brave Search API's privacy notice](https://api-dashboard.search.brave.com/privacy-policy) and [Discord's privacy policy](https://discord.com/privacy). GitHub hosts these documents and public support issues under its [privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). Contact the operator to identify the providers and processing locations used by your installation.

## Storage, retention and deletion

The bot stores operational records in a persistent SQLite database. Operator-controlled snapshots and backups may contain the same information. Provider connections use HTTPS; infrastructure access controls protect the deployment. The application does not itself encrypt its SQLite database or backups, and it does not provide end-to-end encryption of debate content.

We retain information only while needed for the purposes above or as required by law. The current software has no automatic time-based purge schedule; retention review and broader deletion require operator action. Leaving a server or removing the bot does not automatically delete its database.

Deleting or editing a Discord message updates its status and invalidates affected analysis, but **previous text and revision history may remain in the bot's database**. A separate privacy request is needed to remove those stored copies.

You can use:

- `/profile settings analysis:false` to stop future profile analysis.
- `/profile settings visibility:private` to restrict profile views through the bot.
- `/profile correct` to attach a correction or exclude an observation.
- `/profile remove-insights` to delete generated profile observations, disable analysis and prevent regeneration from old matches.

These commands do not erase underlying match transcripts, results, audit records, training history or backup copies. For broader access, correction or deletion, use the contact route above. We will remove or de-identify relevant data we control unless limited retention is legally required, address copies held by service providers where applicable, and handle affected backups so a later restore does not undo the request. We cannot erase independently retained copies controlled by other Discord members or replace requests you must make directly to Discord about its own records.

## Your rights, eligibility and changes

Depending on your location, you may have rights to access, correct, delete or receive your personal information, restrict or object to processing, withdraw consent, or complain to a data-protection authority. Contact the operator to exercise applicable rights.

The bot is intended only for people eligible to use Discord under its age requirements and applicable law. Contact the operator if you believe information from an ineligible child has been collected.

We update this policy when practices change and revise the effective date. Material changes will be communicated through the relevant Discord server or another reasonable channel, with any notice or consent required by law. Using the bot does not waive your privacy rights. See the [Terms of Service](https://github.com/KianBahasadri/argument-arena/blob/main/TERMS.md).
