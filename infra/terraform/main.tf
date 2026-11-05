resource "docker_image" "bot" {
  name         = var.image
  platform     = var.platform
  keep_locally = true
}

resource "docker_network" "bot" {
  name     = var.name
  internal = false # Outbound Discord HTTPS and Gateway WebSocket; no published ports.
}

resource "docker_volume" "state" {
  name = "${var.name}-state"
  lifecycle {
    prevent_destroy = true
  }
}

resource "docker_container" "bot" {
  name                  = var.name
  image                 = docker_image.bot.image_id
  user                  = "10001:10001"
  restart               = "unless-stopped"
  must_run              = true
  init                  = true
  read_only             = true
  network_mode          = "bridge"
  destroy_grace_seconds = 30
  stop_timeout          = 30
  stop_signal           = "SIGTERM"
  wait                  = true
  wait_timeout          = 120
  memory                = 256
  log_driver            = "json-file"
  log_opts = {
    "max-size" = "10m"
    "max-file" = "3"
  }
  security_opts = ["no-new-privileges:true"]
  capabilities {
    drop = ["ALL"]
  }
  networks_advanced {
    name = docker_network.bot.name
  }
  tmpfs = { "/tmp" = "rw,noexec,nosuid,size=16m,mode=1777" }
  env = [
    "AA_DATA_DIR=/var/lib/argument-arena",
    "AA_DISCORD_TOKEN_FILE=/run/secrets/discord-token",
    "AA_GUILD_ID=${var.guild_id}",
    "AA_SYNC_COMMANDS=${var.sync_commands}",
    "AA_LOG_LEVEL=INFO",
  ]
  mounts {
    type   = "volume"
    source = docker_volume.state.name
    target = "/var/lib/argument-arena"
  }
  mounts {
    type      = "bind"
    source    = var.secrets_host_path
    target    = "/run/secrets"
    read_only = true
  }
  healthcheck {
    test         = ["CMD", "argument-arena", "healthcheck"]
    interval     = "15s"
    timeout      = "5s"
    start_period = "30s"
    retries      = 4
  }
  # Default destroy-before-create plus a stable name prevents overlapping Gateway clients.
  lifecycle {
    create_before_destroy = false
  }
}
