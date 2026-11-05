output "container_name" {
  value = docker_container.bot.name
}

output "state_volume" {
  value = docker_volume.state.name
}

output "server" {
  value = { identity = var.server_identity, os = var.server_os, platform = var.platform }
}
