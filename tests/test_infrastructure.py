import importlib.util
import unittest
from pathlib import Path

import yaml

spec = importlib.util.spec_from_file_location(
    "render", Path(__file__).resolve().parents[1] / "scripts/render_manifests.py"
)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class InfrastructureTests(unittest.TestCase):
    def resources(self, **kwargs):
        return {
            r["kind"] + "/" + r["metadata"]["name"]: r
            for r in yaml.safe_load_all(renderer.render("ghcr.io/example/bot:1.0", "123", **kwargs))
        }

    def test_nonroot_restricted_single_replica_with_dynamic_storage(self):
        resources = self.resources()
        deployment = resources["Deployment/bot"]["spec"]
        self.assertEqual(deployment["replicas"], 1)
        self.assertEqual(deployment["strategy"]["type"], "Recreate")
        pod = deployment["template"]["spec"]
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        self.assertFalse(pod["automountServiceAccountToken"])
        container = pod["containers"][0]
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertIn("readinessProbe", container)
        claim = resources["PersistentVolumeClaim/data"]["spec"]
        self.assertEqual(claim["storageClassName"], "openebs-hostpath")
        self.assertEqual(claim["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(claim["resources"]["requests"]["storage"], "1Gi")
        self.assertFalse(
            any(
                r["kind"] in ("PersistentVolume", "Service", "Ingress", "Secret")
                for r in resources.values()
            )
        )

    def test_claim_allows_consumer_placement_and_nonroot_database_writes(self):
        resources = self.resources()
        self.assertNotIn("volumeName", resources["PersistentVolumeClaim/data"]["spec"])
        pod = resources["Deployment/bot"]["spec"]["template"]["spec"]
        self.assertNotIn("nodeName", pod)
        data = next(item for item in pod["volumes"] if item["name"] == "data")
        self.assertEqual(data, {"name": "data", "persistentVolumeClaim": {"claimName": "data"}})
        security = pod["securityContext"]
        self.assertEqual(security["fsGroup"], security["runAsUser"])
        self.assertEqual(security["fsGroup"], security["runAsGroup"])
        self.assertEqual(security["fsGroupChangePolicy"], "OnRootMismatch")
        container = pod["containers"][0]
        mount = next(item for item in container["volumeMounts"] if item["name"] == "data")
        self.assertEqual(mount["mountPath"], "/var/lib/argument-arena")
        self.assertFalse(mount.get("readOnly", False))

    def test_network_is_default_deny_with_dns_and_only_public_https_egress(self):
        resources = self.resources()
        deny = resources["NetworkPolicy/default-deny"]["spec"]
        self.assertEqual(deny["policyTypes"], ["Ingress", "Egress"])
        self.assertNotIn("ingress", deny)
        egress = resources["NetworkPolicy/bot-egress"]["spec"]["egress"]
        self.assertEqual({p["port"] for p in egress[0]["ports"]}, {53})
        self.assertEqual(egress[1]["ports"], [{"protocol": "TCP", "port": 443}])
        self.assertIn("100.64.0.0/10", egress[1]["to"][0]["ipBlock"]["except"])

    def test_credential_rotation_changes_the_pod_template(self):
        original = self.resources()["Deployment/bot"]["spec"]["template"]
        rotated = self.resources(credentials_revision=2)["Deployment/bot"]["spec"]["template"]
        self.assertNotEqual(original["metadata"], rotated["metadata"])
        self.assertEqual(original["spec"], rotated["spec"])
        for revision in (0, -1, 1.5, True, "2\n  invalid: true"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.resources(credentials_revision=revision)

    def test_private_images_and_template_injection_validation(self):
        pod = self.resources(pull_secret="ghcr-pull")["Deployment/bot"]["spec"]["template"]["spec"]
        self.assertEqual(pod["imagePullSecrets"], [{"name": "ghcr-pull"}])
        renderer.render("ghcr.io/example/bot@sha256:" + "a" * 64, "123")
        for value in (
            "bot:latest",
            "bot",
            "ghcr.io/example/bot",
            "bot@sha256:short",
            "bot:1\n  privileged: true",
            "${bad}",
        ):
            with self.assertRaises(ValueError):
                renderer.render(value, "123")

    def test_guild_and_provider_values_cannot_inject_template_content(self):
        for guild in ("", "0", "-1", "١", str(2**64), "123\n  invalid: true"):
            with self.assertRaises(ValueError):
                renderer.render("bot:1", guild)
        for options in (
            {"llm_model": 'model"\n  invalid: true'},
            {"llm_endpoint": "https://opencode.ai/inference/openai/v1/chat/completions"},
            {"llm_endpoint": "https://user:secret@example.com/chat"},
            {"llm_endpoint": "http://example.com/chat"},
            {"llm_endpoint": 'https://example.com/chat"\n  invalid: true'},
        ):
            with self.assertRaises(ValueError):
                renderer.render("bot:1", "123", **options)


if __name__ == "__main__":
    unittest.main()
