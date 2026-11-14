mock_provider "docker" {
  override_during = plan
  mock_resource "docker_image" {
    defaults = { image_id = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  }
}

variables {
  server_os         = "test adapter OS"
  server_identity   = "offline-test.invalid"
  docker_host       = "ssh://operator@offline-test.invalid:22"
  platform          = "linux/amd64"
  image             = "example.invalid/arena@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  secrets_host_path = "/test/secrets"
  guild_id          = "123456789012345678"
}

run "secure_runtime" {
  command = plan # Provider is mocked; this never contacts Docker or a server.
  assert {
    condition     = docker_container.bot.user == "10001:10001" && docker_container.bot.read_only && docker_container.bot.init
    error_message = "Runtime must be non-root, read-only, and forward signals."
  }
  assert {
    condition     = docker_container.bot.restart == "unless-stopped" && docker_container.bot.destroy_grace_seconds == 30 && docker_container.bot.wait
    error_message = "Restart, graceful stop and readiness must be configured."
  }
  assert {
    condition     = length(docker_container.bot.ports) == 0 && !docker_network.bot.internal
    error_message = "Only outbound connectivity is needed; never publish ports."
  }
  assert {
    condition     = contains(docker_container.bot.security_opts, "no-new-privileges:true") && contains(one(docker_container.bot.capabilities).drop, "ALL")
    error_message = "Container privileges must be restricted."
  }
  assert {
    condition = anytrue([
      for mount in docker_container.bot.mounts :
      mount.target == "/var/lib/argument-arena" && mount.type == "volume" && mount.source == docker_volume.state.name
    ])
    error_message = "State must live in the managed named volume."
  }
  assert {
    condition = anytrue([
      for mount in docker_container.bot.mounts :
      mount.target == "/run/secrets" && mount.type == "bind" && mount.read_only && mount.source == var.secrets_host_path
    ])
    error_message = "Secrets must be mounted read-only by path, never uploaded into state."
  }
  assert {
    condition = docker_container.bot.env == toset([
      "AA_DATA_DIR=/var/lib/argument-arena",
      "AA_DISCORD_TOKEN_FILE=/run/secrets/discord-token",
      "AA_GUILD_ID=123456789012345678",
      "AA_SYNC_COMMANDS=true",
      "AA_LOG_LEVEL=INFO",
      "AA_LLM_KEY_FILE=",
      "AA_SEARCH_KEY_FILE=",
      "AA_LLM_MODEL=gpt-4.1-mini",
      "AA_LLM_ENDPOINT=https://api.openai.com/v1/chat/completions",
    ]) && length(docker_container.bot.upload) == 0
    error_message = "Only non-secret configuration belongs in Terraform."
  }
  assert {
    condition     = output.container_name == "argument-arena" && output.state_volume == "argument-arena-state"
    error_message = "Resource names must remain stable across upgrades."
  }
}

run "repeat_plan" {
  command = plan
  assert {
    condition     = docker_container.bot.image == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    error_message = "An unchanged digest must resolve to the same image ID."
  }
}

run "disable_sync" {
  command = plan
  variables {
    sync_commands = false
    platform      = "linux/arm64"
  }
  assert {
    condition     = contains(docker_container.bot.env, "AA_SYNC_COMMANDS=false") && docker_image.bot.platform == "linux/arm64"
    error_message = "Command sync and target architecture must be configurable."
  }
}

run "reject_incomplete_or_unsafe_inputs" {
  command = plan
  variables {
    server_os         = ""
    server_identity   = ""
    docker_host       = "tcp://unprotected.invalid:2375"
    platform          = ""
    image             = "example.invalid/arena:latest"
    secrets_host_path = "/"
    guild_id          = "18446744073709551616"
    name              = "invalid installation name"
  }
  expect_failures = [var.server_os, var.server_identity, var.docker_host, var.platform, var.image, var.secrets_host_path, var.guild_id, var.name]
}

run "runtime_provider_configuration" {
  command = plan
  variables {
    llm_enabled    = true
    search_enabled = true
    llm_model      = "operator-model"
    llm_endpoint   = "https://api.example.org/v1/chat/completions"
  }
  assert {
    condition     = contains(docker_container.bot.env, "AA_LLM_KEY_FILE=/run/secrets/llm-key") && contains(docker_container.bot.env, "AA_SEARCH_KEY_FILE=/run/secrets/search-key") && contains(docker_container.bot.env, "AA_LLM_MODEL=operator-model")
    error_message = "Providers must receive file references and non-secret runtime configuration."
  }
}

run "reject_unsafe_provider_configuration" {
  command = plan
  variables {
    llm_model    = "contains whitespace"
    llm_endpoint = "https://user:secret@example.org/endpoint"
  }
  expect_failures = [var.llm_model, var.llm_endpoint]
}
