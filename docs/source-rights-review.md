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
