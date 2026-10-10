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

- Verify every tile ID in the output against source, not only the first and
  last samples (the prototype currently samples first/last plus counts).
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
