# Repository instructions

## Hard rule: OpenCode Go only

Use **OpenCode Go exclusively** for Argument Arena's LLM features and model evaluations. Select models from the current Go catalog and send inference requests only to `https://opencode.ai/inference/go/...`.

Do not use OpenCode's pay-as-you-go Models API, direct model-provider APIs, or an automatic fallback outside Go. Do not enable paid extra usage or change account billing settings. If a model is unavailable through Go, report that result and keep ordinary match management working.

Keep API keys in the ignored `.secrets/llm-key` file and the existing Kubernetes Secret. Never print credentials or commit secret values.
