variable "kubeconfig_path" {
  type        = string
  description = "Operator kubeconfig path, outside this repository."
  default     = "~/.kube/config"
}

variable "image" {
  type        = string
  description = "Published container image, preferably pinned by digest."
  validation {
    condition     = can(regex("^([A-Za-z0-9._:-]+/)*[A-Za-z0-9._-]+(:[A-Za-z0-9_][A-Za-z0-9_.-]*|@sha256:[a-f0-9]{64})$", var.image)) && !endswith(var.image, ":latest")
    error_message = "Use a versioned image tag or digest rather than latest."
  }
}

variable "guild_id" {
  type        = string
  description = "Intended Discord server snowflake; not a secret."
  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.guild_id)) && try(tonumber(var.guild_id) < 18446744073709551616, false)
    error_message = "Use a positive unsigned 64-bit Discord server ID."
  }
}

variable "llm_model" {
  type    = string
  default = "claude-haiku-5-5"
  validation {
    condition     = can(regex("^[A-Za-z0-9._:/-]{1,100}$", var.llm_model))
    error_message = "Use a model identifier without whitespace or quotes."
  }
}

variable "llm_judge_model" {
  type        = string
  default     = "gemini-4-argon"
  description = "OpenCode Go model for judging when a match does not override it."
  validation {
    condition     = can(regex("^[A-Za-z0-9._:/-]{1,100}$", var.llm_judge_model))
    error_message = "Use a model identifier without whitespace or quotes."
  }
}

variable "llm_endpoint" {
  type    = string
  default = "https://opencode.ai/inference/go/openai/v1/chat/completions"
  validation {
    condition     = contains(["https://opencode.ai/inference/go/openai/v1/chat/completions", "https://opencode.ai/inference/go/openai/v1/responses"], var.llm_endpoint)
    error_message = "Use an OpenCode Go Chat Completions or Responses endpoint."
  }
}

variable "pull_secret" {
  type        = string
  default     = ""
  description = "Optional existing registry Secret in argument-arena namespace. Empty for public images."
  validation {
    condition     = var.pull_secret == "" || can(regex("^[a-z0-9][a-z0-9.-]*$", var.pull_secret))
    error_message = "Use a valid Kubernetes Secret name."
  }
}

variable "credentials_revision" {
  type        = number
  default     = 1
  description = "Increment after changing files in .secrets/ to upload credentials and restart the bot."
  validation {
    condition     = var.credentials_revision >= 1 && floor(var.credentials_revision) == var.credentials_revision
    error_message = "Use a positive integer credential revision."
  }
}
