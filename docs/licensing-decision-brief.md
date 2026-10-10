# Licensing decision brief — 10 October 2026

Research from primary sources, **not legal advice**. Items not checked against a
primary source are marked UNVERIFIED. The owner decides; nothing here is
approved until they say so.

## Findings

| Source | Verdict | Required actions |
|---|---|---|
| OpenStreetMap: tiles, lanes, limits, road info, routing graph | **Safe to approve** with actions | Map credit "© OpenMapTiles © OpenStreetMap contributors" (an (i) button is acceptable), also on the About screen with links to openstreetmap.org/copyright and openmaptiles.org ([OpenMapTiles](https://github.com/openmaptiles/openmaptiles#license) requires visible credit). Each release states "Data under the Open Database Licence (ODbL 1.0)" with link; add the licence link inside the lane/limit/road-info files and the routing manifest ([ODbL §4.2, §4.3, §4.6](https://opendatacommons.org/licenses/odbl/1-0/)). The public release satisfies the §4.6 offer. |
| OS Open Names (GB search) | **Safe to approve** with actions | "Contains OS data © Crown Copyright and database rights 2026. Contains Royal Mail data © Royal Mail copyright and database right 2026. Contains National Statistics data © Crown copyright and database right 2026", plus a link to the [Open Government Licence v3](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/), in About and release notes. |
| OSNI gazetteers (NI streets and towns) | **Safe to approve** with actions | LPS line, already written into the search file when NI records exist; also add it to About, with the OGL link. |
| Overture places | **Approve only with a change** | The release must carry the [CDLA Permissive 2.0](https://cdla.dev/permissive-2-0/) text, the Apache-2.0 text, the full [Foursquare NOTICE](https://opensource.foursquare.com/places-notice-txt/), and a modification notice ("Foursquare data was transformed to the Overture schema; modified by DriveMate: merged, de-duplicated, reduced to five fields"). Credit Overture/Foursquare in About. Fix the README places licence line. Because OSM points are mixed in, label places squares "ODbL, includes CDLA/Apache/CC0 data" (interpretation UNVERIFIED). |
| **Mapillary** (lane arrows and speed-limit signs from photos; caches) | **Do not publish / do not use in the app** | [Mapillary Terms](https://www.mapillary.com/terms) §5 forbids use "in connection with real-time navigation or route guidance, such as to turn-by-turn route guidance". §11 forbids merely redistributing content and requires logo and link. No CC BY-SA or ODbL licence was found for map features, so the repo's "CC BY-SA 4.0" labels in limits.py and arrows.py are unsupported. The lawful route (§13) is to use the photos to check and edit OpenStreetMap by hand; fixes then return under ODbL. |

## Owner decisions needed

1. Approve OSM and OS Open Names publication with the credits above (recommended: yes).
2. Approve Overture places once the licence texts and NOTICE ship with the release (recommended: yes, after that change), or drop Overture.
3. **Mapillary:** stop using Mapillary-derived values in the app and the release, pause the Mapillary workflow steps, and remove the published caches. Recommended: yes. Note that the scheduled weekly build on `main` still includes Mapillary steps. Changing `main` needs the owner's approval.
4. Northern Ireland postcodes: ask LPS in writing (a draft can be prepared), or accept none offline.

Not checked: the app's current attribution screens, and whether vector tiles legally count as a produced work or a database (the actions above cover both).
