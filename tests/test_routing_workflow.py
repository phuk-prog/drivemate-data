from pathlib import Path
import subprocess
import unittest
import yaml


class RoutingWorkflowTest(unittest.TestCase):
    def test_failed_graph_builder_pipeline_cannot_be_hidden_by_tail(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/map-data.yml'
        workflow = yaml.safe_load(path.read_text())
        graph = next(step['run'] for step in workflow['jobs']['routing']['steps']
                     if step.get('name') == 'Build the road graph')
        prefix = graph.split('export PATH=', 1)[0]
        self.assertIn('pipefail', prefix)
        failed = subprocess.run(['bash', '-c', prefix + 'false | tail -n 1'],
                                capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn('tags-filter', graph)
        self.assertIn('valhalla_build_tiles -c work/valhalla.json work/base.osm.pbf', graph)

    def test_legacy_clobber_publisher_removed(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/map-data.yml'
        workflow = yaml.safe_load(path.read_text())
        publication = next(step['run'] for step in workflow['jobs']['routing']['steps']
                           if step.get('name') == 'Publish the road graph')
        self.assertIn('publish_routing_data.py', publication)
        self.assertNotIn('--clobber', publication)
        self.assertIn('GITHUB_RUN_ATTEMPT', publication)
