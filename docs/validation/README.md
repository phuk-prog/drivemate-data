# Published-data audit — 10 October 2026

All checks here were read-only. Existing releases and Android files were not changed.
The working tree began at data `50906eb3e82d42b938425f6f1f83aa3a319718b8`.

## Inputs and results

- Map pointer: `map-data-uk/latest.json`; manifest: `map-data-20261008-bootstrap/manifest.json`.
  Manifest SHA-256 `1ce4935da3277bbf90d2cf5abd91c8d16fd3f025de1fbce84f5215cbc73c63ae` matches the pointer.
- All **999** listed map assets match their manifest sizes and SHA-256 hashes.
  This bootstrap inventory contains cameras, 217 lane files and 780 places archives,
  plus the 1,638,441,575-byte PMTiles map. There is no limits, roadinfo, offline search,
  charge-zone, source-inventory or build-quality asset in that inventory.
- Every places archive was parsed by the existing `coverage_audit.audit()`.
  4,523,868 records in valid archives were checked. Six additional archives fail
  the UK coordinate envelope; the detailed report lists them. Eight blocking
  core-city gaps concern missing limits/roadinfo. This audit does **not** pass.
- Four z14 PMTiles samples decode with transportation, building and housenumber
  features using pmtiles 3.4.1 and mapbox-vector-tile 2.2.0. This checks samples and
  schema availability, not all geometry, actual entrances or verified addresses.
- Graph generation: `routing-uk-20261009-r37969596182-a1`, Valhalla 3.6.3.
  Compressed chunk: 1,016,384,059 bytes, SHA-256
  `cec7a8309f83f62af8a3c479ed4ffebec9c5e2b556b22e13d468b1bfd24872c1`.
  Gzip CRC, decoded bounds, 2,800,936,960-byte length and SHA-256
  `4d88c7d2fca0b6dfc4f79cf09a128595d61f198da2b55942e123e5c7c9f729f3`
  verified before native execution. Four benchmark routes each ran three times
  with stable summaries; all 11 additional UK connectivity probes found routes.
  Neither desktop result proves Android compatibility or legal ground truth.

## Reproduction

Use a Python virtual environment with the pinned source-CI dependencies, plus
pyvalhalla 3.6.3 for native graph checks. Use `gh release download --repo
phuk-prog/drivemate-data` to retrieve the named manifest/pointer and each asset
from its manifest `tag`. Store lanes and places in directories of those names.
For every manifest file, stream SHA-256 and compare byte length before parsing;
compare the manifest itself against the pointer's `manifest_sha256` first.
Do not infer integrity from an HTTP success or filename alone.

From the data checkout, with downloaded map layers under `$MAP_AUDIT_ROOT`:

```bash
PYTHONPATH=scripts python - <<'PY'
import json, os
from pathlib import Path
from coverage_audit import audit
root = Path(os.environ['MAP_AUDIT_ROOT'])
report = audit(root)
print(json.dumps(report, indent=2))
raise SystemExit(bool(report['errors']))
PY
```

For the graph, concatenate manifest chunks in the declared order, verify each
compressed hash and size, stream-decode with the declared byte limit, then check
the final decoded size/hash. The current generation has one chunk, so:

```bash
python scripts/benchmark_offline_routes.py graph.tar.gz.part00 benchmark.json \
  --graph-manifest routing-uk.json --repeats 3
python scripts/routing_connectivity.py --graph verified-uk.tar --report connectivity.json
```

The benchmark verifies decoded identity itself; it does not independently verify
the compressed chunk manifest. The connectivity CLI must receive the already
verified decoded graph. Keep the source metadata and tool versions beside results.

## Correction and release boundary

`places.py` now counts and excludes non-finite/out-of-envelope coordinates before
indexing, with regression tests based on the failing archive regions. This does
not repair or replace the existing release. The broad envelope also contains some
non-UK land; precise territorial validation remains outstanding. Full rebuilt
map/search/graph verification, feature provenance/rights and Android UK execution
are still required. Validation-only builds omit unreviewed Mapillary observations;
they must not be labelled as validation of the imagery-enhanced live pipeline.
