variable "server_os" {
  description = "Operator-recorded server OS; deliberately unspecified until deployment."
  type        = string
  nullable    = false
  validation {
    condition     = length(trimspace(var.server_os)) > 0
    error_message = "Record the server OS after the owner supplies it."
  }
}

variable "server_identity" {
  description = "Expected Docker daemon Name, verified by scripts/preflight.py."
  type        = string
  nullable    = false
  validation {
    condition     = length(trimspace(var.server_identity)) > 0
    error_message = "Provide the expected Docker daemon identity."
  }
}

variable "docker_host" {
  description = "Explicit unix://, npipe:// or ssh:// Docker endpoint; no implicit local target."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^(unix:///[^[:space:]]+|npipe:////[^[:space:]]+|ssh://[A-Za-z0-9_.-]+@([A-Za-z0-9_.-]+|\\[[0-9a-fA-F:]+\\])(:[0-9]{1,5})?)$", var.docker_host))
    error_message = "Use an explicit local socket or ssh://user@host[:port] endpoint."
  }
}

variable "platform" {
  description = "Owner-selected Linux container architecture, independently of server OS."
  type        = string
  nullable    = false
  validation {
    condition     = contains(["linux/amd64", "linux/arm64"], var.platform)
    error_message = "Select linux/amd64 or linux/arm64 after identifying the server runtime."
  }
}

variable "image" {
  description = "Published bot image pinned by registry manifest digest; no mutable tags."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", var.image))
    error_message = "Supply a registry image reference ending in @sha256:<64 lowercase hex digits>."
  }
}

variable "secrets_host_path" {
  description = "Pre-provisioned absolute directory on the Docker daemon host, containing discord-token."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^/[^\n\r,]+$", var.secrets_host_path))
    error_message = "Provide an absolute, dedicated directory in the Linux Docker runtime filesystem."
  }
}

variable "guild_id" {
  description = "The owner's Discord guild snowflake, passed as a string to avoid numeric rounding."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.guild_id)) && try(tonumber(var.guild_id) < 18446744073709551616, false)
    error_message = "Provide a positive unsigned 64-bit Discord guild ID as a string."
  }
}

variable "name" {
  description = "Stable installation name; do not change once durable state exists."
  type        = string
  default     = "argument-arena"
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,47}$", var.name))
    error_message = "Use a lowercase installation name of at most 48 letters, digits or hyphens."
  }
}

variable "sync_commands" {
  description = "Synchronize this build's guild commands once per login; never on reconnect."
  type        = bool
  default     = true
  nullable    = false
}
