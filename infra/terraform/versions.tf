terraform {
  required_version = "~> 1.13.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
}

provider "docker" {
  host = var.docker_host
  # Keys and verified known_hosts stay in the operator's external SSH configuration/agent.
  ssh_opts = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]
}
