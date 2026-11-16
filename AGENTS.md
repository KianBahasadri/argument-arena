# Agent instructions

Always use the maximum reasoning effort supported by the configured model for
every LLM call, including analysis, research, judging, training grading, and bot
battles. This policy applies to existing calls and any new LLM integrations.

For [MiniMax M3.1 Flash](https://platform.minimax.io/docs/guides/text-generation)
through OpenCode Go, explicitly request `max`:

- Chat Completions: `reasoning_effort="max"`.
- Responses: `reasoning={"effort": "max"}`.

Preserve this policy when changing models or providers: use the new model's
highest supported setting and keep coverage for every task and API path. Do not
lower reasoning effort for cost or latency unless the user explicitly requests it.
