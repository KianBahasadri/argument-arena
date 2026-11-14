provider "kubernetes" {
  config_path = pathexpand(var.kubeconfig_path)
}

locals {
  documents = [for document in split("\n---\n", templatefile("${path.module}/resources.yaml.tftpl", {
    image                = var.image
    pull_secret          = var.pull_secret
    guild_id             = var.guild_id
    llm_model            = var.llm_model
    llm_judge_model      = var.llm_judge_model
    llm_endpoint         = var.llm_endpoint
    credentials_revision = var.credentials_revision
  })) : yamldecode(document)]
  resources = { for document in local.documents : "${document.kind}/${document.metadata.name}" => document if document.kind != "Namespace" }
}

resource "kubernetes_namespace_v1" "arena" {
  metadata {
    name = "argument-arena"
    labels = {
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/audit"   = "restricted"
      "pod-security.kubernetes.io/warn"    = "restricted"
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_secret_v1" "credentials" {
  metadata {
    name      = "bot-credentials"
    namespace = kubernetes_namespace_v1.arena.metadata[0].name
  }

  data_wo = merge(
    { "discord-token" = try(trimspace(file("${path.module}/../.secrets/discord-token")), "") },
    { for name in ["llm-key", "search-key"] : name => trimspace(file("${path.module}/../.secrets/${name}")) if fileexists("${path.module}/../.secrets/${name}") }
  )
  data_wo_revision = var.credentials_revision

  lifecycle {
    precondition {
      condition     = try(length(trimspace(file("${path.module}/../.secrets/discord-token"))) > 0, false)
      error_message = "Save the Discord token in the ignored .secrets/discord-token file before planning."
    }
  }
}

resource "kubernetes_manifest" "arena" {
  for_each   = local.resources
  manifest   = each.value
  depends_on = [kubernetes_secret_v1.credentials]
}
