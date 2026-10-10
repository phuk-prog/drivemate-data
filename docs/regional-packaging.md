# DriveMate regional map packaging — implementation pilot

Decision (2026-10-10): **one UK-wide low-zoom PMTiles (z0–9)** plus
**z10–14 detail packages grouped by z8 Web Mercator parent tiles**.
A z8 tile is 1.40625 degrees wide in longitude; actual ground distance
varies with latitude. Dense z8 sections are automatically subdivided to
z9 and if needed z10. Default hard limit **200,000,000 bytes** for each
detailed package. This is a starting engineering constraint, not yet
a field-measured optimal download size.

Why not England/Scotland halves or counties? Halves can exceed release
constraints and force large rebuilds; county boundaries vary in size and
complicate deterministic tile ownership. Tiny z12 packages have too much
inventory overhead. A z8 hierarchical partition balances management and
regional downloads while keeping the exact same MVT source payloads.

### Prototype commands (nonpublishing)

Run after obtaining and SHA-256 verifying an existing complete UK PMTiles
archive (e.g. from a previously verified release):

```bash
python3 scripts/region_pmtiles.py \
  --source path/to/drivemate.pmtiles --output work/region-plan --plan-only

# Pilot covering Manchester city centre, without producing a UK-wide new release
python3 scripts/region_pmtiles.py \
  --source path/to/drivemate.pmtiles --output work/manchester-pilot --pilot 8/126/82
```

The pilot writes `base.pmtiles`, Manchester-only detail package(s),
and an unpublished `regional-manifest.json` with SHA-256 and byte lengths.
It refuses pre-existing output content. Nothing is uploaded or activated in
Android. All detailed z10–14 tiles have one parent z8 key (or one subdivided
child); low zoom z0–9 is unique to base. Physical map content is copied
without editing roads, house numbers or polygons.

### Critical remaining gates

- **Implemented:** compare every expanded tile ID and raw gzip MVT payload
  byte-for-byte with the source during each region export. Verify real UK
  geometry and renderer behaviour separately.
- Check real Manchester artifact size, rendering and downloaded data consumption.
- Implement region selection in Android without affecting existing installed
  complete-UK source; test missing region, zoom crossing, download resume,
  multi-package generation matching and rollback.
- Keep **national Valhalla graph** initially. Road routing and road junction
  restrictions MUST NOT terminate at map detail region borders. If graph
  partitioning is ever pursued, routing topology edges, turn restrictions,
  border overlaps and cross-boundary driving must be tested independently.
- Map data layers such as lanes (half-degree) and places (quarter-degree)
  remain in their existing format. Their geographical boundary format is
  distinct from Web Mercator z8 PMTiles; never assume they are the same.
- Source licence and feature lineage requirements remain outstanding.
  Do not publicly release pilot regions until legally cleared.
- Keep existing complete-UK PMTiles and Android file formats unchanged until
  the region consumer is verified. Do not disturb the in-progress validation-only
  UK build; regional splitting should use an already verified source archive.

### Completion condition

Only count regional delivery implemented when real (not synthetic) regions
pass content and renderer tests, compatibility is confirmed on Android,
boundary transitions work, and a single immutable verified manifest
and rollback process covers every component.

### Why the base includes zoom 9

Adaptive z8 → z9 → z10 subdivision must never strand a z9 tile in a
region subdivided below z9. Keeping every z0–9 tile in the nationwide
base ensures that each tile has exactly one owner. Regional overlays
then exclusively contain z10–14 tiles. This design refinement does not
alter the currently installed Android map.

### Automated nonpublishing real UK pilot

The `.github/workflows/regional-pilot.yml` workflow is a read-only pilot
on the development branch. It is triggered only by relevant changes to the
regional packaging source/workflow or explicit manual dispatch. Its GitHub
Actions concurrency group is exactly `map-data` so it cannot compete with
the currently running full UK map build using that group. It downloads the
unchanged, already audited legacy release archive and requires exact SHA-256
`8ec2a5cd5e4373a5d75243c1aa46ccb40adb3a8dd9b821f06a3b2c765f9cf069`
and byte length `1638441575` before any processing.

The workflow makes an unpublished Manchester pilot and checks the
resulting archives' PMTiles/MVT format. It uploads **only the compact
manifest and validation reports**, not the map payloads (licence review
outstanding). The source release and Android app remain unchanged. A real
pilot run's successful results must be observed before its data pipeline
is considered tested. The experiment remains constrained by the verified
historical archive, not the newest in-progress UK map build.


### Verified first real UK pilot — 10 October 2026

Run [38031100907](https://github.com/phuk-prog/drivemate-data/actions/runs/38031100907)
**passed** on data commit `7cd5ee2b4550b787cdc8c1ac3280f3c4a34c5219`.
Actual source: the checksum-verified 1,638,441,575-byte UK PMTiles
(`8ec2a5cd5e4373a5d75243c1aa46ccb40adb3a8dd9b821f06a3b2c765f9cf069`).

| Verified file | Compressed bytes | Tiles | SHA-256 |
|---|---:|---:|---|
| UK base z0–9 | 18,185,774 | 1,063 | `f584f1c2b38bda01292b2e526db52488944cd2608cde17e2bb2081db1a1b33fa` |
| Manchester detail z10–14 | 116,261,842 | 5,456 | `21f33b60200ba1dfbfa2e46d45bb8ec7f8afe66c826a25e6b3f7476fa07fcd2e` |

All 6,519 expanded addressed tiles were matched to their source IDs
and compressed payloads by the exporter; both generated archives also
passed the complete gzip/MVT archive verifier. The 116 MB detail pack is
below the 200 MB target, but this is **one** example, not proof that all
UK regions meet it. No map assets were uploaded or installed by the pilot.

Android-side pure selection and boundary tests were committed in
`phuk-prog/DriveMate` at `6d92e843e2ad80995f967ae621a60d89276ccfe4`.
**These do not activate the regions, prove renderer compatibility or
remove Stage 1 publication/licensing blockers.** Do not prematurely
replace the existing whole-UK map archive or graph.

Next: confirm Android CI, implement checksum-verified package acquisition
and safe renderer integration on the development branch, check adjacent
regional seams and missing-region fallback, and run real on-device
rendering/navigation tests before exposing regional downloads.


### Whole-UK partition and reproducible exports — 10 October 2026

Planned locally against the published, SHA-256-verified UK archive
(`8ec2a5cd…f069`, 1,638,441,575 bytes; release manifest
`map-data-20261008-bootstrap`, `1ce4935d…63ae`). Evidence:
`docs/validation/uk-regional-plan-20261010.json`.

- **206 z8 detail packages + one 18.2 MB base; no root needs subdivision.**
  Largest is `region-z8-x127-y85` (west London / Thames Valley) at an
  estimated 143.6 MB; Manchester 116.3 MB. All are under the 200 MB limit.
- 144 packages are under 1 MB (coastal and sea slivers). They cost almost
  nothing to verify; multi-region batch requests handle them in bulk.
- Manchester's companion list, filtered to the real release inventory:
  12 lane squares and 28 places squares. The current release has no
  `limits-*`/`roadinfo-*` squares and no charge-zone or offline-search file,
  so none are listed. This is a known gap in the current release, not an
  exporter fault.

**Reproducibility fix.** pmtiles 3.4.1 gzips each archive's root
directory and metadata with the current time, so the same region exported
twice gave different SHA-256 values. The CI pilot's recorded hashes
(`f584f1c2…`, `21f33b60…`) were therefore one-off. `region_pmtiles.py` now
fixes the gzip timestamp. Tile payloads were always copied raw. Two local
exports of Manchester are now byte-identical and pass the full verifier:

| File | Bytes | Tiles | SHA-256 (reproducible) |
|---|---:|---:|---|
| base | 18,185,774 | 1,063 | `f1e06acc85e8277baf52b5ab859de2b24add12fd968d100d7b485f796e89d823` |
| region-z8-x126-y82 | 116,261,842 | 5,456 | `8544a3ddef349ab2731c91bf6a2431c0e4a4c7ada87de3853e323e53a55253d8` |

A future publisher can now re-derive a region and get the hashes recorded
in the ledger. A regression test re-exports at a different clock time and
requires identical hashes.


### Publication path (implemented, off by default) — 10 October 2026

Every weekly or validation build now exports and fully verifies all regional
packages from the map it has just built (about 3 minutes) and keeps the
manifest and per-archive reports as evidence. **Staging for publication
happens only when the repository variable `PUBLISH_REGIONAL_MAPS` is `true`.**
That variable should be set only after the licensing and Manchester
acceptance gates are approved.

`scripts/region_publication.py` refuses pilots, partial exports, archives
cut from a different map, and any archive whose size or SHA-256 changed since
verification. It moves the set into `out/regions/` as
`regional-base.pmtiles`, `region-z*-x*-y*.pmtiles` and a
`regional-manifest.json` with status `published`. `publish_map_data.py`
re-checks the whole staged set against that manifest and the release's
`drivemate.pmtiles` before any upload. The phone trusts the regional
manifest only through the release manifest's SHA-256, which `latest.json`
pins. The full stage-and-validate path was run on the real UK archive:
207 archives were staged and validated.
