# Source rights review — 10 October 2026

This is an engineering inventory of primary-source terms, not a blanket grant of
rights or a claim that every existing published feature is cleared. No new live
map publication is authorised by a passing fingerprint check.

| Source / primary evidence | Reuse conditions and current decision |
|---|---|
| [OpenStreetMap copyright](https://www.openstreetmap.org/copyright) and [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | Commercial reuse is possible with attribution and applicable database share-alike/source-access obligations. Preserve source fingerprints and make the derivative database/licence available where required; rendered map attribution remains necessary. This does not establish accuracy or unrestricted ownership. |
| [OS Open Names documentation](https://docs.os.uk/os-downloads/products/os-open-names) and [OS OpenData terms](https://www.ordnancesurvey.co.uk/documents/licences/os-opendata-licence.pdf) | GB place/street/postcode data, not a complete postal-address database or NI dataset. Preserve OS, Royal Mail and National Statistics notices and verify current product-specific third-party conditions before distribution. UPRN products cannot substitute for postal addresses. |
| [Overture attribution](https://docs.overturemaps.org/attribution/) | Current places include CDLA Permissive 2.0 sources, Foursquare under Apache 2.0 with its NOTICE and modification notice, and AllThePlaces under CC0. The merged five-field generator currently drops upstream lineage. Generic Overture credit is insufficient to establish all required notices for a specific release. Record the exact Overture release and retain source/licence/NOTICE information before publication. Other themes have different licences, including ODbL. |
| [Mapillary terms](https://www.mapillary.com/terms), sections 3, 11, 12 | Image/User Content licences and extracted API data have different conditions. Developer applications require registration; extracted-data integration requires a visible Mapillary logo and link. Terms describe permitted commercial purposes but do not establish unrestricted independent redistribution of observation caches. Repository credentials/application scope and cache redistribution remain unresolved. Image recognition is not human verification of a legal restriction. Do not clear this source from a CC BY-SA image notice alone. |
| [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/) | Publisher declares raster/vector data public domain. The pinned executable downloads the vector SQLite archive from naciscdn.org. Fingerprint the actual archive; this is low-resolution context, not road-level ground truth. |
| [OSM water polygons](https://osmdata.openstreetmap.de/data/water-polygons.html) | ODbL-derived source. Preserve OSM attribution and applicable database obligations; distinguish these inputs from the main UK PBF. |
| [OSM lake lines v12](https://github.com/acalcutt/osm-lakelines/tree/v12) | Repository LICENSE is MIT for software; README describes an OSM Planet PBF to lake polygon/centre-line workflow. Do not use a software licence as proof that derived geographical data is free of upstream obligations. Retain OSM provenance and review the archive's data terms. |
| [OpenMapTiles profile](https://github.com/openmaptiles/planetiler-openmaptiles/tree/91516fdf477915b1a985015811049b9b96c7f87e) and [schema licence](https://github.com/openmaptiles/openmaptiles#license) | Planetiler 0.10.1 pins this profile. Its generated output notice calls for visible OpenMapTiles and OpenStreetMap credit. Source/database terms still apply independently of software licensing. |
| [Wikidata structured-data terms](https://www.wikidata.org/wiki/Wikidata:Licensing) | Structured data is CC0; optional translation cache is now inventoried when present. The inventory does not yet record individual queries, revisions or redirected URLs. |

## Publication blockers and compliant path

The current bootstrap release lacks source inventory and complete feature lineage.
The existing five-field places format is retained for Android compatibility; a
future separate provenance/notice sidecar must preserve upstream obligations.
Mapillary cache redistribution and observation verification must be resolved or
the next release must use a documented OSM-only alternative. Preserve previous
working releases and disclose the unavailable imagery detail. New production
publication remains held while these questions and generated-data failures remain.

`source_inventory.py --planetiler-sources work/sources` now records the three
required ancillary archives and an optional Wikidata cache. Missing required
ancillary files fail the complete-build inventory. Older schema-1 inventories
remain readable; that backward compatibility does not clear their rights gaps.
All entries continue to say `not_independently_verified`. Fingerprints are
reproducibility evidence, never a permission decision.

## Places provenance/notice sidecar

`places.py` now also writes one nationwide `places-provenance.json` beside the
unchanged five-field `places-<row>_<col>.json.gz` tiles (Android still reads only
the tiles). It records per-source record counts after merge and de-duplication
(Overture, OSM, OS Open Names), input and rejected-coordinate counts, a per-dataset
breakdown of kept Overture records from the parquet `sources[].dataset` column
(`unavailable` when that column is absent), and the Overture release passed with
`--overture-release` (`unknown` when not supplied). The map workflow resolves the
latest release with `overturemaps releases latest`, downloads exactly that
release and passes it on; if the release cannot be resolved it records `unknown`.
Licence and notice wording is copied only from the table above and lives in
`scripts/places_provenance.py`. `validate_build.py` checks the sidecar's totals
against the audited tiles, and the publisher validates its structure and requires
it for navigation-data publication.

What it does NOT establish: it is not legal clearance and says
`rights_review_status: "not_independently_verified"`. It does not contain the
Foursquare NOTICE file text, a modification notice, or exact OS/Royal Mail/National
Statistics notice wording; it does not give per-record lineage inside the tiles;
and per-dataset counts reflect what the Overture input declares, not verified
upstream ownership. The publication blockers above remain until those obligations
are reviewed and satisfied.

## Northern Ireland postcode and street search — research, 10 October 2026

Research from primary sources, not legal clearance. Items marked UNVERIFIED
could not be confirmed from a primary source.

| Source | NI content | Offline redistribution in the app | Decision |
|---|---|---|---|
| ONSPD / NSPL (ONS), BT rows | Postcode centroids from LPS Pointer | **Not allowed.** ONS: "If you also use the Northern Ireland data (postcodes starting with "BT"), you need a separate licence for commercial use direct from Land and Property Services"; the linked LPS End User Licence (Oct 2011) permits "your own internal business use… all other uses are prohibited". | Do not bundle |
| postcodes.io | Serves the same ONSPD BT rows | Same restriction as ONSPD | Do not bundle; current online lookups need LPS confirmation before any commercial release |
| Code-Point Open (OS) | GB only | n/a | No NI value |
| [OSNI Open Data – Gazetteer – Streetnames](https://admin.opendatani.gov.uk/dataset/osni-open-data-gazetteer-streetnames) | All NI street names with Irish Grid coordinates; no postcodes or addresses | Allowed under OGL v3 per data.gov.uk listing and LPS statement ("including it in your own product or application") | **Use**, with attribution: "Contains LPS Intellectual Property © Crown copyright and database right (year) This information is licensed under the terms of the Open Government Licence" |
| OSNI Open Data – Gazetteer – Place Names | 336 towns/villages (label points) | OGL | Use, with the same attribution |
| OpenStreetMap `addr:postcode` in NI | Non-authoritative, coverage UNVERIFIED | ODbL with attribution | Fallback only, labelled as non-authoritative |
| LPS Pointer, NISRA Central Postcode Directory, paid Code-Point | Addresses / postcodes | Licensed / restricted | Do not use |

Open questions that need **written** confirmation from LPS
(mapping.helpdesk@finance-ni.gov.uk) before acting:
1. Whether BT postcode centroids may be shipped in a free or Play Store app.
2. That an HSENI note saying OSNI mapping is exempt from OGL does not apply
   to the OGL-marked gazetteers.

Not verified here: OpenDataNI returned 403, so the gazetteer's field names,
record count and currency (resources dated 2015–2021) are UNVERIFIED. A newer
LPS licence (January 2026) was seen only on a secondary site.

Recommended next step: add the OSNI street and place gazetteers to offline search
(converting Irish Grid EPSG:29902/29903 to WGS84), keeping their attribution.
Do this once a GitHub runner can download them.
