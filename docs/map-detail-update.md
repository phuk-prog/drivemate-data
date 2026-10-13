# Complete OSM retention and daily updates

Base: data main `a446223222fc31847c778b5c48355a09966f7999`.

Prepared for isolated GitHub validation; the default-branch schedule activates only after validation and promotion:
- Preserve the exact supplied OSM PBF as verified source chunks, including all nodes, ways, relations and tags present in that extract. This is not edit history or proof that OSM has surveyed every road.
- The builder parses the real PBF before capturing it. Publication verifies chunk hashes and matches the whole source to the map input's recorded SHA-256, size and URL before any upload.
- Preserve full exported road tags and coordinate precision in separate deterministic `road-details-*` backend files. Phone lane files keep their existing selection and bounded schema, with mapped level/width/change tags added.
- Prepare a conservative per-region change planner with matching verified-receipt checkpoints. Failed or absent sources cannot erase coverage or advance progress.
- Export all geographic features with original IDs, tags and geometry into app-readable regional gzip NDJSON. Large features have a global pack. Compressed disk spools bound UK memory/disk use. Separate relation packs preserve all tags and ordered typed member references and roles.
- Check the OSM source daily through the last verified published checkpoint. Source or builder changes trigger a checked build; unchanged observations skip the expensive work. Monday forces a refresh of existing other-source feeds and retains Sunday's acceptance checks.
- Verify source checksums before and after download; the checkpoint, exact source archive, feature and relation datasets must agree before publication. Immutable release shards and checked reuse avoid reuploading unchanged regional/detail assets. Validation branches cannot publish map or routing pointers.

Not yet implemented or activated:
- Real regional source observations and extraction/build adapters. Existing regional map packages still split a national build.
- Daily schedule activation on main after the new validation. MD5 is only a change signal; SHA-256 identifies the exact downloaded bytes.
- New app readers and map layers for generic detailed features, exact markings, kerbs, entrances, opening hours or accessibility. Retained information is not automatically drawn or used for guidance.
- Real UK size/memory/capacity proof for the richer backend export and source retention. Source archive chunks add upload/storage bytes and must stay outside default phone downloads.

Focused exporter, relation, source, probe and publication tests pass. Full local preflight reports unavailable pmtiles, mapbox-vector-tile, pyproj and shapely libraries; network installation was aborted. This is unavailable evidence, not a passing full gate. The user authorised upload/build; GitHub validation installs the real dependencies and runs canonical preflight before a new map build. Android compilation/device proof is also unavailable here. Current Android manifest entry/byte limits are enforced before any upload.

The old-code refresh `38120645154`, attempt 2, was cancelled and publication skipped. Only a new exact-source successful validation and production run establishes that these data are published. The phone still needs new readers/UI for the detail packs. Missing lane facts stay unknown; live traffic remains a separate provider feed and no TomTom responses are stored.
