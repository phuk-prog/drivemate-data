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

## Road-seam continuity and offline graph samples — 9 October 2026

`grid_tiles.tiles_for_polyline()` now assigns existing lane and speed-limit
geometries to every half-degree square touched by every line segment,
including intermediate squares with **no vertices** and geometric border
cases. Previous code indexed only line vertices and could omit a long
crossing segment from an intervening download region. Both writers use the
same geometry helper; focused source tests cover skipped cells, negative
longitudes, reversal, exact borders and corner crossings.

The Valhalla UK routing workflow retains the original six **blocking** route
smoke checks. Additional north/south and cross-region sample journeys now
produce a diagnostic JSON report during real graph builds. An unsuccessful
extra diagnostic probe is logged for investigation, not used to fabricate
legal turns or automatically edit the map. Source-regression tests validate
diagnostic logic using synthetic route responses; **no new full UK graph
build is claimed by these tests**.

Caution: complete OSM node connectivity, junction legality, turn restrictions,
physical lanes and every region border require independent comprehensive
audits; geometric tile continuity and sample routes do not prove them.

## Junction topology diagnostics (development only)

Added `scripts/junction_topology.py` to inspect **real shared OSM node IDs**
from Osmium OPL way records. It reports sample network components, possibly
unconnected major road ends, malformed adjacent node references and candidate
interior shared-node conflicts between explicitly grade-separated roads.

**Critical safeguards:** a visually crossing road with two different node IDs
is never invented as a junction; a bridge-to-road transition at a way endpoint
is not automatically considered erroneous; legitimate residential/service
dead ends are not reported as major-road failures; uncertain cases are reported
for human review, never added to navigable topology.

Two source-sample audits (Manchester and Belfast) are added to the next full
UK map build using reference-complete Osmium extracts. The extra reports go
into the workflow summary/work directory, **not** into a published routing
graph or the Android app. These are diagnostics, not evidence of all UK
road-connected components, legal turn permissions, individual lane links,
restriction relations, or updated ground truth. No production graph build
or road-data correction is claimed until independently run and checked.

## Sampled OSM turn restriction relations — development, diagnostic only

`scripts/restriction_audit.py` now parses OSM `type=restriction` relations
from Osmium OPL alongside road way/node reference lists. For a **simple
via-node relation**, it checks that the referenced approach and exit ways
contain the via node and flags suspicious explicit-one-way orientation.
For **via-way relations**, it checks whether the from/via/to ways actually
share OSM nodes, without assuming a visible geometric crossing is a junction.
It also records unknown/missing references, conditional restrictions, vehicle
exceptions and complex formats; none is automatically treated as a proven
illegal turn. Valid cul-de-sacs or separate bridge levels are not fabricated
as new road connections.

The next full UK map workflow adds **Manchester and Belfast** relation
diagnostics using Osmium smart extracts configured to complete
`type=restriction` relation members. JSON reports stay in the build workspace;
only summaries appear in the workflow output. Source unit tests use synthetic
OPL records. Passing source CI is **not evidence** of the actual UK relation
results, Valhalla's interpretation, real-world road signs, or legally permitted
routes. A full graph build and targeted driving-route verification are required
before considering any changes to live routing behavior.
