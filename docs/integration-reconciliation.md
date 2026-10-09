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
