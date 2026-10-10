# DriveMate map data

Open map data for the DriveMate navigation app, rebuilt every week by
[`.github/workflows/map-data.yml`](.github/workflows/map-data.yml). New builds publish
immutable dated releases and a verified file manifest. The small `latest.json` asset on
the [`map-data-uk` release](../../releases/tag/map-data-uk) advertises a generation only
after all its assets have uploaded and their SHA-256 hashes and sizes match.

| File | What it is |
|---|---|
| `drivemate.pmtiles` | Map pictures for the UK (the app streams just the parts it needs) |
| `lanes-<row>_<col>.json` (in release `map-data-uk-extra`, like limits, roadinfo, charge zones and search) | Lane counts and lane arrows, in half-degree squares (arrows from OpenStreetMap, plus painted arrows seen in Mapillary street photos where the map has none: `turn:lanes:source=mapillary`) |
| `mapillary-arrows-cache.json.gz` | The painted arrows found near each junction, kept so each week only re-checks the oldest |
| `places-<row>_<col>.json.gz` | Businesses, places and streets, merged and de-duplicated, quarter-degree squares |
| `limits-<row>_<col>.json` | Speed limits on roads, in half-degree squares: `{"ways": [[kmh, [[lon, lat], ...]], ...], "src": ["o"\|"m", ...], "dir": [...], "source": "..."}`. `ways` is what the app reads; `src` says where each came from (`o` OpenStreetMap, `m` speed-limit signs seen in Mapillary street photos, used only where OpenStreetMap has no limit, or for Welsh roads still mapped at 30 where 20 mph signs confirm the change); `dir` holds limits known for one direction of a two-way road only (points in travel order; not used by the app yet). Roads with no known limit are left out |
| `mapillary-signs-cache.json.gz` | The speed-limit signs found in each area, kept so each week only re-checks the oldest areas |
| `limit-checks.md` (on the run's summary page) | Limits that look wrong, including Welsh roads mapped at 30 mph where photos show 20 mph signs |
| `roadinfo-<row>_<col>.json` | Road warnings and turn landmarks, in half-degree squares: speed bumps, hazard signs, speed cameras, level crossings, toll booths, schools, traffic lights, stop signs and well-known named places (fuel stations, pubs, places of worship, fast food, supermarkets). Same layout as an Overpass answer, so the app reads it with no signal |
| `search-offline-uk.tsv.gz` | Offline search (about 31 MB): every postcode in Great Britain (1.7 million), every named street, and towns, villages, stations, hospitals, schools, airports, ferry ports and motorway services, from OS Open Names. Format below |
| `cameras-uk.json` | Speed / red-light / average-speed cameras and level crossings |
| `charge-zones-uk.json` | Charge and emission zones with what each means for a car: London Congestion Charge and London-wide ULEZ (official TfL boundaries), Birmingham Clean Air Zone (inside the A4540 Middleway, traced from OpenStreetMap because the council's own file is not openly licensed), and the other Clean Air Zones / Scottish LEZs mapped in OpenStreetMap |

Also, in the separate `routing-uk` release: `routing-uk.json` and `valhalla-uk-<date>.tar.gz.partNN`, the
whole-UK road graph (Valhalla 3.6.3) for routes worked out on the phone with no signal. The phone
downloads it on Wi-Fi only when you switch it on in Settings; `routing-uk.json` switches to a new
build only after its pieces have uploaded and six test journeys across the UK have worked.

Sources and licences:
- © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/)
- [Overture Maps](https://overturemaps.org) places (CDLA Permissive 2.0 / ODbL as published)
- Painted lane arrows and speed-limit signs: [Mapillary](https://www.mapillary.com) contributors. Imagery licensing alone does not establish permission to redistribute API detections or derived routing data; applicable derivative-data terms require separate review.
- Contains OS data © Crown copyright and database right (OS Open Names, Open Government Licence); Contains Royal Mail data © Royal Mail copyright and database right; Contains National Statistics data © Crown copyright and database right
- Congestion Charge and ULEZ boundaries: contains Transport for London data (London Datastore, Open Government Licence v2)

Source licence declarations are preliminary. `source-inventory.json` records observed
files and fingerprints, not legal clearance or complete feature provenance. Optional
upstream sources and Planetiler ancillary downloads still require review before new
live publication. Open access alone does not establish redistribution rights.

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

### Offline search file format (`search-offline-uk.tsv.gz`)

Gzip-compressed UTF-8 text, one record per line, fields separated by TAB.

- Line 1 (header): `#drivemate-search-offline` TAB `1` (format version) TAB build date TAB credits (show these).
- Every other line: `key` TAB `type` TAB `name` TAB `area` TAB `lat` TAB `lon`
  - `key`: the name in lower case, accents removed, `&` → `and`, only a–z, 0–9 and single spaces
    kept. Postcodes have no space (`sk82ez`). **Lines are sorted by key** (byte order), so everything
    starting with what the driver typed is together: stream until past it, or binary-search an
    unpacked copy.
  - `type` (one letter): `P` postcode, `R` street, `C` city, `T` town, `V` village, `H` hamlet,
    `S` suburb/area, `O` other settlement, `N` railway station, `B` bus/coach station,
    `A` airport/airfield/heliport, `F` ferry terminal/harbour, `M` hospital/hospice/care home,
    `E` school/college/university, `U` motorway services.
  - `name`: as shown (`Menai Grove`). Welsh/Gaelic names are extra lines for the same place.
    **Empty for postcodes**: show the key in capitals with a space before the last three
    characters (`sk82ez` → `SK8 2EZ`).
  - `area`: `Town, Postcode district` (`Cheadle, SK8`), or the council/county when there is no
    town; for postcodes just the town.
  - `lat`, `lon`: WGS84, 4 decimal places (~10 m). Postcode = its centre; street = a point on it.
- Northern Ireland isn't in OS Open Names, so its postcodes and streets aren't in this file.

Example lines:
```
menai grove	R	Menai Grove	Cheadle, SK8	53.3956	-2.1942
sk82ez	P		Cheadle	53.3954	-2.1942
```

The painted-arrow and speed-limit-sign steps need a free Mapillary key as the repository secret `MAPILLARY_TOKEN`
(Settings → Secrets and variables → Actions). Without it they keep last week's arrows and signs.

National Highways (checked Oct 2026) has no free download of permanent speed limits (its open
Network Model has none; its keyed APIs cover only roadworks limits and roadside features), so
nothing is taken from it.
