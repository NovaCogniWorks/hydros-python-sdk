"""Prevent ready-but-unsubscribed custom-agent deployments and credential baking."""
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class CustomAgentDeploymentTest(unittest.TestCase):
    def test_runtime_topics_and_pinned_images(self):
        for path in (ROOT / 'deploy/k3s/custom-agents').glob('*.yaml'):
            with self.subTest(manifest=path.name):
                deployment = next(yaml.safe_load_all(path.read_text()))
                container = deployment['spec']['template']['spec']['containers'][0]
                env = {item['name']: item for item in container['env']}
                self.assertEqual(env['HYDROS_METRICS_TOPIC']['value'],
                                 '/hydros/data/edges/{hydros_cluster_id}')
                self.assertIn('@sha256:', container['image'])
                for name, item in env.items():
                    if any(word in name for word in ('PASSWORD', 'TOKEN', 'USERNAME')):
                        self.assertNotIn('value', item)
                self.assertEqual(deployment['spec']['replicas'], 1)

    def test_local_environment_files_are_not_baked_into_images(self):
        self.assertIn('**/env.properties', (ROOT / '.dockerignore').read_text())
        for kind in ('power', 'pump'):
            dockerfile = (ROOT / f'custom-agent/{kind}/Dockerfile').read_text()
            self.assertIn(f'touch /opt/hydros/custom-agent/{kind}/env.properties', dockerfile)


if __name__ == '__main__':
    unittest.main()
