provider "kubernetes" {
  config_path = pathexpand(var.kubeconfig_path)
}

locals {
  documents = [for document in split("\n---\n", templatefile("${path.module}/resources.yaml.tftpl", {
    image        = var.image
    worker_name  = var.worker_name
    storage_path = var.storage_path
    pull_secret  = var.pull_secret
    guild_id     = var.guild_id
    llm_model    = var.llm_model
    llm_endpoint = var.llm_endpoint
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

resource "kubernetes_manifest" "arena" {
  for_each   = local.resources
  manifest   = each.value
  depends_on = [kubernetes_namespace_v1.arena]
}
