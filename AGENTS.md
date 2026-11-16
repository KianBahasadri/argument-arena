# AGENTS.md

Argument Arena is a Discord bot for managed debates, evidence checks, judging and reasoning practice.

## Rules

- Always use the maximum reasoning effort supported by the configured model for
  every LLM call, including analysis, research, judging, training grading and bot
  battles. This applies to existing calls and every new LLM integration.
- For [MiniMax M3.1 Flash](https://platform.minimax.io/docs/guides/text-generation)
  through OpenCode Go, explicitly request `reasoning_effort="max"` for Chat
  Completions and `reasoning={"effort": "max"}` for Responses.
- Preserve the maximum-reasoning policy when changing models or providers, and
  retain coverage for every task and API path. Do not lower reasoning effort for
  cost or latency unless the user explicitly requests it.
- Deploy after every feature change. Complete validation, commit and push the
  change, wait for CI and image publication to pass, deploy the published image,
  and verify the rollout and bot readiness before reporting completion.

## Documentation (read/write)

- **Read first:** For how this repo works, start at `docs/README.md`, then
  open only the topic files you need. Do not re-derive behavior from
  filenames alone when a doc covers it.
- **Before non-trivial changes:** Check the relevant doc so you match
  existing patterns.
- **After behavior changes:** Update the **one** topic file under `docs/`
  that owns that fact. Do not copy the same detail into AGENTS.md,
  README.md, or multiple docs.
- **Regenerate vs patch:** `docs/README.md` records the commit it was
  generated from; `git diff <sha>..HEAD --stat` shows what changed since.
  Prefer the `generate_docs` skill when docs are broadly stale or many
  topics shifted; for small, targeted edits, patch the single topic file
  (and `docs/README.md` if you add/remove a topic).
- `CLAUDE.md` is a symlink to this file.

Do not put implementation detail in this file — it lives under `docs/`.
