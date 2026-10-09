# DriveMate map data

Open map data for the DriveMate navigation app, rebuilt every week by
[`.github/workflows/map-data.yml`](.github/workflows/map-data.yml). New builds publish
immutable dated releases and a verified file manifest. The small `latest.json` asset on
the [`map-data-uk` release](../../releases/tag/map-data-uk) advertises a generation only
after all its assets have uploaded and their SHA-256 hashes and sizes match.

| File | What it is |
|---|---|
| `drivemate.pmtiles` | Map pictures for the UK (the app streams just the parts it needs) |
| `lanes-<row>_<col>.json` | Lane counts and lane arrows, in half-degree squares |
| `places-<row>_<col>.json.gz` | Businesses, places and streets, merged and de-duplicated, quarter-degree squares |
| `cameras-uk.json` | Speed / red-light / average-speed cameras and level crossings |

Sources and licences:
- © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/)
- [Overture Maps](https://overturemaps.org) places (CDLA Permissive 2.0 / ODbL as published)
- Contains OS data © Crown copyright and database right (OS Open Names, Open Government Licence)

Only open data is published here.

The app checks for a new generation daily while in use. Identical regional files stay
cached; changed files are downloaded when needed and checked before replacing the
previous file. This is a whole-file update, not a binary patch. The online PMTiles map
streams requested portions; an optional offline archive still needs a full replacement.

`scripts/publish_map_data.py` splits new generations across main and extra releases to
avoid GitHub's 1,000-asset limit. Published data assets are never overwritten. A failed
upload or checksum check leaves the previous pointer selected.

The bootstrap repair inventories the existing legacy assets, preserving their hashes.
It archives and verifies `build-info.txt` before removing that metadata from the full
legacy release to make room for `latest.json`. It does not regenerate road data or claim
that an earlier partial build covered every UK lane/place square. Missing regional data
remains unavailable, rather than being treated as an empty area.
