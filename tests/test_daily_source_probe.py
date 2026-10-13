import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daily_source_probe as probe

URL = "https://download.geofabrik.de/europe/united-kingdom-latest.osm.pbf"
PIPELINE = "a" * 64
DATA = b"observed source fixture"
SIGNAL = hashlib.md5(DATA, usedforsecurity=False).hexdigest() + "  united-kingdom-latest.osm.pbf\n"


def prior():
    return {"schema": 1, "source_url": URL, "change_signal": probe.parse_signal(SIGNAL, URL), "pipeline_sha256": PIPELINE}


class DailySourceProbeTests(unittest.TestCase):
    def test_stable_changed_pipeline_and_weekly_force(self):
        self.assertFalse(probe.decide(URL, SIGNAL, PIPELINE, prior())["rebuild"])
        self.assertTrue(probe.decide(URL, SIGNAL, "b" * 64, prior())["rebuild"])
        changed = "b" * 32 + "  united-kingdom-latest.osm.pbf\n"
        self.assertTrue(probe.decide(URL, changed, PIPELINE, prior())["rebuild"])
        new_url = URL.replace("united-kingdom", "england")
        self.assertIn("source URL changed", probe.decide(new_url, SIGNAL.replace("united-kingdom", "england"), PIPELINE, prior())["reasons"])
        self.assertEqual(["forced weekly rebuild"], probe.decide(URL, SIGNAL, PIPELINE, prior(), True)["reasons"])

    def test_missing_invalid_prior_rebuilds(self):
        for value in (None, {}, {"schema": True}, prior() | {"change_signal": {"algorithm": "sha256", "value": "a" * 64}}):
            self.assertTrue(probe.decide(URL, SIGNAL, PIPELINE, value)["rebuild"])

    def test_invalid_observations_never_become_unchanged(self):
        for signal in (None, "", "a" * 64 + " united-kingdom-latest.osm.pbf", SIGNAL + SIGNAL,
                       SIGNAL.replace("united-kingdom", "england"), "x" * 4097):
            with self.subTest(signal=signal), self.assertRaises(ValueError):
                probe.decide(URL, signal, PIPELINE, prior())

    def test_url_validation(self):
        for url in (URL.replace("https", "http"), URL.replace("download.geofabrik.de", "evil.example"),
                    URL.replace("download.geofabrik.de", "download.geofabrik.de@evil.example"),
                    URL + "?x=1", URL.replace("/europe/", "/../"),
                    URL.replace("/europe/", "/%2e%2e/"), URL.replace("download.geo", "download.geo\n")):
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.source_url(url)

    def test_checkpoint_checks_bytes_and_distinguishes_algorithms(self):
        with tempfile.TemporaryDirectory() as folder:
            pbf = Path(folder) / "source.osm.pbf"
            pbf.write_bytes(DATA)
            checkpoint = probe.build_checkpoint(URL, SIGNAL, SIGNAL, PIPELINE, pbf)
            self.assertEqual("md5", checkpoint["change_signal"]["algorithm"])
            self.assertEqual(hashlib.sha256(DATA).hexdigest(), checkpoint["source_sha256"])
            self.assertEqual(len(DATA), checkpoint["source_bytes"])
            for after in ("b" * 32 + "  united-kingdom-latest.osm.pbf\n", ""):
                with self.assertRaises(ValueError):
                    probe.build_checkpoint(URL, SIGNAL, after, PIPELINE, pbf)
            pbf.write_bytes(b"different source")
            with self.assertRaises(ValueError):
                probe.build_checkpoint(URL, SIGNAL, SIGNAL, PIPELINE, pbf)

    def test_pipeline_deterministic_and_includes_code_config_not_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / ".github/workflows").mkdir(parents=True)
            (root / "scripts/build.py").write_text("pass\n")
            (root / "scripts/profile.yml").write_text("schema: 1\n")
            (root / ".github/workflows/map-data.yml").write_text("name: build\n")
            (root / "requirements.txt").write_text("dependency==1\n")
            initial = probe.pipeline_fingerprint(root)
            self.assertEqual(initial, probe.pipeline_fingerprint(root))
            (root / "scripts/source-checkpoint.json").write_text('{"generated": "today"}')
            (root / "config").mkdir()
            (root / "config/daily-source-checkpoint.json").write_text('{"generated": "today"}')
            self.assertEqual(initial, probe.pipeline_fingerprint(root))
            (root / "scripts/profile.yml").write_text("schema: 2\n")
            self.assertNotEqual(initial["pipeline_sha256"], probe.pipeline_fingerprint(root)["pipeline_sha256"])
            (root / "scripts/build.py").unlink()
            with self.assertRaises(ValueError):
                probe.pipeline_fingerprint(root)

    def test_cli_failed_checkpoint_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            signal, pbf, output = [root / name for name in ("source.md5", "source.pbf", "checkpoint.json")]
            signal.write_text(SIGNAL)
            pbf.write_bytes(DATA)
            args = ["checkpoint", "--source-url", URL, "--signal-before", str(signal), "--signal-after", str(signal),
                    "--pipeline-sha256", PIPELINE, "--pbf", str(pbf), "--output", str(output)]
            self.assertEqual(0, probe.main(args))
            old = output.read_text()
            self.assertEqual(PIPELINE, json.loads(old)["pipeline_sha256"])
            pbf.write_bytes(b"damaged")
            with self.assertRaises(SystemExit):
                probe.main(args)
            self.assertEqual(old, output.read_text())


if __name__ == "__main__":
    unittest.main()
