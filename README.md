# DriveMate map data

Open map data for the DriveMate navigation app, rebuilt every week by
[`.github/workflows/map-data.yml`](.github/workflows/map-data.yml) and published as the
[`map-data-uk` release](../../releases/tag/map-data-uk):

| File | What it is |
|---|---|
| `drivemate.pmtiles` | Map pictures for the UK (the app streams just the parts it needs) |
| `lanes-<row>_<col>.json` | Lane counts and lane arrows, in half-degree squares (arrows from OpenStreetMap, plus painted arrows seen in Mapillary street photos where the map has none: `turn:lanes:source=mapillary`) |
| `mapillary-arrows-cache.json.gz` | The painted arrows found near each junction, kept so each week only re-checks the oldest |
| `places-<row>_<col>.json.gz` | Businesses, places and streets, merged and de-duplicated, quarter-degree squares |
| `limits-<row>_<col>.json` | Speed limits on roads, in half-degree squares |
| `cameras-uk.json` | Speed / red-light / average-speed cameras and level crossings |
| `charge-zones-uk.json` | Charge and emission zones (ULEZ, Clean Air Zones, Scottish LEZs) with what each means for a car |

Sources and licences:
- © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/)
- [Overture Maps](https://overturemaps.org) places (CDLA Permissive 2.0 / ODbL as published)
- Painted lane arrows: [Mapillary](https://www.mapillary.com) contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- Contains OS data © Crown copyright and database right (OS Open Names, Open Government Licence)

Only open data is published here.

The painted-arrow step needs a free Mapillary key as the repository secret `MAPILLARY_TOKEN`
(Settings → Secrets and variables → Actions). Without it the step keeps last week's arrows.
