import importlib.util
from pathlib import Path
import unittest

import yaml


spec = importlib.util.spec_from_file_location("render", Path(__file__).resolve().parents[1] / "scripts/render_manifests.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class InfrastructureTests(unittest.TestCase):
    def resources(self, **kwargs):
        return {r["kind"] + "/" + r["metadata"]["name"]: r for r in yaml.safe_load_all(renderer.render("ghcr.io/example/bot:1.0", **kwargs))}

    def test_nonroot_restricted_single_replica_with_retained_static_storage(self):
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
        volume = resources["PersistentVolume/argument-arena-data"]["spec"]
        self.assertEqual(volume["persistentVolumeReclaimPolicy"], "Retain")
        self.assertNotIn("hostPath", volume)
        self.assertEqual(volume["nodeAffinity"]["required"]["nodeSelectorTerms"][0]["matchExpressions"][0]["values"], ["demure"])
        self.assertEqual(resources["PersistentVolumeClaim/data"]["spec"]["storageClassName"], "")
        self.assertFalse(any(r["kind"] in ("Service", "Ingress", "Secret") for r in resources.values()))

    def test_network_is_default_deny_with_dns_and_only_public_https_egress(self):
        resources = self.resources()
        deny = resources["NetworkPolicy/default-deny"]["spec"]
        self.assertEqual(deny["policyTypes"], ["Ingress", "Egress"])
        self.assertNotIn("ingress", deny)
        egress = resources["NetworkPolicy/bot-egress"]["spec"]["egress"]
        self.assertEqual({p["port"] for p in egress[0]["ports"]}, {53})
        self.assertEqual(egress[1]["ports"], [{"protocol": "TCP", "port": 443}])
        self.assertIn("100.64.0.0/10", egress[1]["to"][0]["ipBlock"]["except"])

    def test_private_images_and_template_injection_validation(self):
        pod = self.resources(pull_secret="ghcr-pull")["Deployment/bot"]["spec"]["template"]["spec"]
        self.assertEqual(pod["imagePullSecrets"], [{"name": "ghcr-pull"}])
        renderer.render("ghcr.io/example/bot@sha256:" + "a" * 64)
        for value in ("bot:latest", "bot", "ghcr.io/example/bot", "bot@sha256:short", "bot:1\n  privileged: true", "${bad}"):
            with self.assertRaises(ValueError):
                renderer.render(value)


if __name__ == "__main__":
    unittest.main()
