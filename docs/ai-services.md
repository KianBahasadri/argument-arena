# AI services

`providers.py` owns provider access. `Assistance` in `assistance.py` owns debate
analysis, research, disputes and judging. Training uses the same LLM adapter; its
workflow is documented in [training](training.md).

## Provider boundary

The async OpenAI SDK talks only to the OpenCode Go endpoints listed in
[configuration](configuration.md). Each task accepts `default` or the single
operator-selected model name; another selection fails with `model_not_enabled`.
The adapter has no alternate provider or billing fallback.

All tasks (`analyze`, `research`, `judge`, `grade`, `battle`) use maximum reasoning
effort. Chat Completions sends `reasoning_effort="max"`; Responses sends
`reasoning={"effort": "max"}`. Responses also sends `store=False`. Both request
JSON objects and cap output at 3000 tokens. Incomplete, truncated or non-object
responses are rejected. SDK retries are disabled because the durable worker owns
retries. Calls have a 25-second overall deadline and 20-second transport timeout.

User data is serialized into a separate message from task policy. Debate messages,
pages and URLs are treated as untrusted data. Models receive no tools. Input over
200000 serialized characters is rejected. A hashed conversation header groups
related requests without exposing the raw match identifier in that header.
Credentials are read from files for each call, allowing rotation.

The custom HTTPS transport validates every DNS result as global, pins the
connection to a validated address, and verifies TLS against the original host.
Only HTTPS port 443 without URL credentials is accepted. Public page redirects
are revalidated; authenticated requests and request bodies cannot redirect.
Responses are limited to two million bytes.

## Claim analysis and evidence

Official messages create revision-specific analysis jobs. Claims retain exact
source quotations, author, message URL, message revision and timestamps. Accepted
kinds are factual, value, opinion, definition, prediction and question. Claim
relations may support, rebut, respond, concede, revise or object to existing claim
IDs in the same supplied context. Topic/approach tags describe passages rather
than personal beliefs. Invented quotes, invalid relations and malformed output
are rejected before writing extracted claims.

Optional ledger notices, fallacy findings, coaching and civility suggestions obey
their enabled flags and message frequencies. Private coaching is delivered to
the author. Civility escalation records a staff-review request and can post to
the configured announcement channel; it does not apply automatic sanctions.

Background research considers factual claims. On-demand checks are independently
controlled; turning background research off does not turn off on-demand checks.
Nonfactual claims are marked not fact-checkable. Stale claims cannot be rechecked
as current.

Brave search fetches actual HTTPS HTML/text pages rather than accepting search
snippets as evidence. Sources retain URL, title, text, retrieval time, SHA-256,
publication date when present, Last-Modified and provenance. Page text is capped
at 12000 characters. Preferred source domains affect search ordering. Participant
HTTPS evidence links from recent disputes can be fetched alongside search results.

The research model can cite only supplied source IDs. A substantive verdict
requires references and a confidence within 0–1. Empty retrieval produces
insufficient evidence without an LLM verdict call. Failed retrieval, credentials
or budgets produce explicit status/history entries rather than factual conclusions.
Evidence flags require a contradicted/partly-supported verdict above the configured
threshold; batched delivery waits 60 seconds and suppresses superseded flags.

Participants can dispute claims or results with a reason and optional HTTPS
source. Claim disputes preserve history and can queue an enabled, budgeted
on-demand recheck. Later contrary evidence on a judged result flags staff review,
withdraws rating eligibility and invalidates generated insights.

## Judging

Final judging uses the nondeleted official transcript and nonstale claims. It
waits for pending analysis/research work, deferring rather than consuming retry
attempts for `waiting_for_evidence`. Failed evidence work remains unassessed.
Live scores are provisional, and feedback-only jobs do not replace procedural
outcomes.

The model returns participant scores and actual message/claim references under
the accepted `arena-v1` weights. Code validates participants, score ranges,
references, sufficiency and feedback before calculating totals and the winner.
Factual accuracy is omitted and remaining weights renormalized when the player
has no traceable assessed factual evidence. Insufficient debate produces an
inconclusive outcome; close totals use the configured tie policy. Audience votes
do not enter the calculation.

Transcript and analysis versions guard provider-call races. A changed snapshot
queues fresh judging rather than closing against outdated evidence. Staff can
resolve stalled judging with an explained outcome. Private feedback is filtered
from other viewers' result panels. Rating effects are documented in
[profiles and ratings](profiles-and-ratings.md).

## Budgets and failures

Debate calls consume daily guild LLM and per-match LLM allowances. Research
consumes daily guild and per-match research allowances, plus on-demand request
counts where applicable. Training consumes the guild LLM allowance. Daily windows
reset at midnight UTC; per-match counters do not reset. Retrying work still obeys
budgets.

`ProviderError` carries a safe status and retry flag. `model_response` turns
malformed model structures into provider failures without swallowing storage
errors. `messages.py` maps known statuses into user instructions without echoing
private service responses. See [operations](operations.md) for worker retry and
recovery mechanics.
