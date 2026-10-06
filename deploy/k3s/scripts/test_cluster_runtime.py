import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cluster_runtime as runtime


class ClusterRuntimeTest(unittest.TestCase):
    def test_cluster_identity_and_secret_loading(self):
        target = "hydros-test"
        meta = {"appEnv": "on-premises", "runtimeConfigSecret": "runtime", "deploymentPolicyConfigMap": "policy"}
        config = {"schemaVersion": 1, "clusterTarget": target, "env": {"DB_PASSWORD": "example", "APP_NAME": "wrong"}}
        policy = {"schemaVersion": 1, "clusterTarget": target, "applications": {"app": {"30-deployment.yaml": {}}}}
        responses = [{"data": {"runtime.json": base64.b64encode(json.dumps(config).encode()).decode()}}, {"data": {"policy.json": json.dumps(policy)}}]
        with patch.object(runtime, "read_object", side_effect=responses) as read:
            env, patches = runtime.load_cluster_runtime(meta, target, "hydros", "app", {"APP_NAME": "app"}, {"APP_NAME"})
        self.assertEqual(env["APP_NAME"], "app")
        self.assertEqual(env["DB_PASSWORD"], "example")
        self.assertEqual(read.call_args.args[:2], (target + "-live-deploy", "hydros"))
        self.assertIn("30-deployment.yaml", patches)
        with self.assertRaises(SystemExit):
            runtime.load_cluster_runtime({"appEnv": "on-premises"}, target, "hydros", "app", {}, set())
        policy["clusterTarget"] = "wrong"
        responses[1]["data"]["policy.json"] = json.dumps(policy)
        with patch.object(runtime, "read_object", side_effect=responses), self.assertRaises(SystemExit):
            runtime.load_cluster_runtime(meta, target, "hydros", "app", {}, set())

    def test_testing_does_not_fetch_private_config(self):
        with patch.object(runtime, "read_object") as read:
            self.assertEqual(runtime.load_cluster_runtime({"appEnv": "testing"}, "test", "hydros", "app", {"X": "1"}, set()), ({"X": "1"}, {}))
            read.assert_not_called()

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl required for local strategic merge")
    def test_resource_and_portal_patch_preserve_runtime_and_image(self):
        def spec(container):
            return {"spec": {"template": {"spec": {"containers": [container]}}}}
        document = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "app"}, **spec({"name": "app", "image": "new-image:tag", "env": [{"name": "URL", "value": "wrong"}], "resources": {"limits": {"cpu": "1"}}})}
        saved = spec({"name": "app", "env": [{"$patch": "replace"}, {"name": "URL", "value": "local"}, {"name": "OTHER", "value": "keep"}]})
        policy = spec({"name": "app", "resources": {"limits": {"cpu": None, "memory": "1Gi"}}, "env": [{"name": "REDIRECT", "value": "https://192.0.2.1:30488"}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "30-deployment.yaml"
            path.write_text(json.dumps(document))
            runtime.apply_cluster_policy(path.parent, {path.name: [saved, policy]})
            container = json.loads(path.read_text())["spec"]["template"]["spec"]["containers"][0]
            self.assertEqual(container["image"], "new-image:tag")
            self.assertEqual({e["name"]: e["value"] for e in container["env"]}, {"URL": "local", "OTHER": "keep", "REDIRECT": "https://192.0.2.1:30488"})
            self.assertNotIn("cpu", container["resources"]["limits"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
