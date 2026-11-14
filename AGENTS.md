# Repository instructions

## Hard rule: OpenCode Go only

Use **OpenCode Go exclusively** for Argument Arena's LLM features and model evaluations. Select models from the current Go catalog and send inference requests only to `https://opencode.ai/inference/go/...`.

Do not use OpenCode's pay-as-you-go Models API, direct model-provider APIs, or an automatic fallback outside Go. Do not enable paid extra usage or change account billing settings. If a model is unavailable through Go, report that result and keep ordinary match management working.

Use one inexpensive Go model for every LLM feature, including judging. Do not configure a separate premium judging model. Gemini 4 Argon, Kimi K3.1 Pro and GLM 5.3 are excluded from the current deployment choice because of their cost.

The selected model is **MiniMax M3.1 Flash** (`minimax-m3.1-flash`). Use it for every LLM feature; per-feature and match settings must not route requests to a different model.

Keep API keys in the ignored `.secrets/llm-key` file and the existing Kubernetes Secret. Never print credentials or commit secret values.
