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

variable "worker_name" {
  type    = string
  default = "demure"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]*$", var.worker_name))
    error_message = "Use the Kubernetes worker node name."
  }
}

variable "storage_path" {
  type    = string
  default = "/var/lib/argument-arena"
  validation {
    condition     = can(regex("^/var/[A-Za-z0-9/_-]+$", var.storage_path))
    error_message = "Use a persistent absolute directory under /var."
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
