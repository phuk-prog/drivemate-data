# Architecture foundation integration

This integration reconciles repair-map-updates at
`4104db3bc07d74bd3ddcaeb6251623d9db290638` with the additional navigation
datasets from `71b1c460af00babb81c1c9428e98e9e983e6c763`.

The publisher preserves checksum-verified immutable assets and accepts the
additional limits, road information, charge zones, offline search, observation
caches and build reports. The production workflow requires the additional
navigation datasets before any upload. Search validation consumes the entire
gzip, checking CRC, sorted records, coordinates, format and attribution.
Quality reports containing errors block publication. These are inventory and
format checks; they do not prove geographic completeness or whole-UK search
coverage. OS Open Names covers Great Britain, not Northern Ireland.

Pointer replacement is recoverable, not atomic: GitHub clobber can remove the
previous asset before replacement succeeds. Promotion failure attempts to
restore the downloaded, verified previous pointer and verifies recovery. A
recovery failure is reported explicitly. External concurrent publishers and
service outages remain risks; the workflow serializes its own runs and routes
its expensive routing build after the map build.

Local validation: 19 Python tests pass, including a simulated deletion followed
by upload failure, corrupted search input, a failed quality report, missing
navigation datasets and inclusion of reconciled assets in the manifest.
Workflow YAML and the serialized routing dependency parse successfully.
No production publication or whole-UK data build has been run for this change.

The SQLite search prototype and synthetic comparative results remain an
experiment. They are not yet integrated into the Android app or publication.

## Source input fingerprints and rights review — 9 October 2026

The new `source-inventory.json` records SHA-256 hashes, sizes and presence
of the exact OpenStreetMap PBF and available Overture places, OS Open Names
archive and Mapillary-derived observation caches. It is included in the
immutable release manifest. A navigation-data publication now refuses a
missing, malformed or inconsistent inventory before uploading.

This is input-file provenance, **not** per-feature lineage or legal clearance.
Planetiler ancillary downloads and the detailed reuse rights of Overture,
OS/Royal Mail sources and Mapillary derivatives still require review. Missing
optional sources are recorded and warned about, not misrepresented as used.
The old release is unchanged until an independently validated production
generation is published.

## Broader map-data geographical quality gates — 9 October 2026

Additional region samples cover **19 more populated UK centres** across England,
Scotland, Wales and Northern Ireland, on top of the four previous nation-capital/
core-city samples. All four previous core checks remain strict for each map
layer; the additional 19 checks require populated **places** tiles. Missing
lane/limit/roadside records at additional sites are flagged as unknown/warnings
rather than fabricating road features.

The quality gate also parses **every** compressed `places-*.json.gz` file, checking
gzip integrity, 5-element record shape, coordinates, and quarter-degree tile
assignment. Corrupt or malformed archives block publication even if they are
outside the sampled centres. Counts and regional observations are recorded
in `build-quality.json` and the workflow summary.

**Explicit limitations:** The city samples do not prove UK geographic
completeness, address coverage, route legal validity, or verified road-level
information. Fully validating those requires external independent reference
data, ground-truth cases and routing topology audits. No new UK-wide data
build or production publication is implied by these source checks.
