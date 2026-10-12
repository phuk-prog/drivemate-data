# Optional regional OSM property index

Status: implemented, experimental and unpublished. Android import and device
compatibility remain pending. No download manifest or publication workflow enables
this package. Existing five-field regional places files retain their format.

`regional_addresses.py` exports mapped address nodes and closed ways from an
explicit public Geofabrik PBF. Source SHA-256, size, URL, replication timestamp,
extract bounding box and ODbL notice accompany the package. A source identity and
ODbL declaration are required; this does not substitute for source rights review.
The source is checked again after extraction. Missing fields and invalid geometries
are counted. Relations and interpolation are intentionally recorded as unsupported,
not invented as individual postal addresses.

Search supports indexed property-prefix, exact postcode and FTS4 street/name token
queries. FTS5 is not used. Input operators are normalised into plain alphanumeric
terms; result counts and query lengths are bounded. The SQLite file is inspected
with `integrity_check`, every record and the word index before same-directory atomic
replacement. Failed/duplicate/empty builds retain the previous file.

Coordinates retain mapped precision. `mapped_node` means an OSM node coordinate;
`outline_average` means the average of outline vertices, not an area-weighted
centroid or a verified entrance. Entrance tags remain unverified observations.
Both postal verification and entrance verification are false, even when a postcode
or an entrance tag exists. No routable vehicle access is inferred.

Reproduce the bounded local experiment (requires `osmium==4.2.0`):

```sh
python3 scripts/regional_addresses.py \
  --pbf /path/to/greater-manchester-261008.osm.pbf \
  --source-url https://download.geofabrik.de/europe/united-kingdom/england/greater-manchester-261008.osm.pbf \
  --out /tmp/manchester-addresses.sqlite \
  --report /tmp/manchester-addresses-report.json
python3 -m unittest discover -s tests -p test_regional_addresses.py -v
```

See `docs/validation/regional-addresses-manchester-20261012.json` for the complete
local package fingerprint, actual row/gap counts and bounded search smoke timing.
These timings describe this host, not an Android device. The PBF, SQLite package
and compressed package are outside Git; only source and aggregate evidence are
committed. Attribution and ODbL obligations must accompany any future distribution.
Regional segmentation preserves useful house numbers; it does not assert nationwide
coverage or force a UK dataset under one file-size limit.
