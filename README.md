# DriveMate map data

Open map data for the DriveMate navigation app, rebuilt every week by
[`.github/workflows/map-data.yml`](.github/workflows/map-data.yml) and published as the
[`map-data-uk` release](../../releases/tag/map-data-uk):

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
