from pathlib import Path
import subprocess
import unittest
import yaml


class RoutingWorkflowTest(unittest.TestCase):
    def test_manual_build_defaults_to_no_publication(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/map-data.yml'
        workflow = yaml.safe_load(path.read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertIs(triggers['workflow_dispatch']['inputs']['validate_only']['default'], True)
        for job in ('build', 'routing'):
            publisher = next(step for step in workflow['jobs'][job]['steps']
                             if step.get('name', '').startswith('Publish'))
            self.assertEqual(publisher['if'],
                             "github.event_name != 'workflow_dispatch' || inputs.validate_only == false")

    def test_oversized_map_keeps_house_numbers_and_stops(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/map-data.yml'
        workflow = yaml.safe_load(path.read_text())
        generator = next(step['run'] for step in workflow['jobs']['build']['steps']
                         if step.get('name', '').startswith('Our own map tiles'))
        self.assertNotIn('--exclude_layers=housenumber', generator)
        oversized = generator.split('-gt 1950000000 ]; then', 1)[1].split('fi', 1)[0]
        self.assertIn('exit 1', oversized)

    def test_validation_checks_capacity_and_uses_osm_only_observations(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/map-data.yml'
        workflow = yaml.safe_load(path.read_text())
        steps = workflow['jobs']['build']['steps']
        capacity = next(i for i, s in enumerate(steps) if s.get('name', '').startswith('Validate dependencies'))
        download = next(i for i, s in enumerate(steps) if s.get('name', '').startswith('OpenStreetMap base'))
        self.assertLess(capacity, download)
        self.assertIn('unified_preflight.py', steps[capacity]['run'])
        # Mapillary removed entirely (owner decision, 10 Oct 2026): no arrow step, OSM-only limits.
        self.assertFalse(any(s.get('name', '').startswith('Painted lane arrows') for s in steps))
        limits = next(s for s in steps if s.get('name', '').startswith('Speed limits'))
        self.assertIn('scripts/limits.py', limits['run'])
        self.assertNotIn('--roads', limits['run'])
        self.assertNotIn('--signs-cache', limits['run'])
        self.assertNotIn('MAPILLARY_TOKEN', str(limits.get('env', {})))
        self.assertNotIn('MAPILLARY_TOKEN', path.read_text())

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
