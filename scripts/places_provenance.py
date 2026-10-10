"""Nationwide provenance/notice sidecar for the merged places tiles.

``places.py`` writes ``places-provenance.json`` beside the unchanged five-field
``places-<row>_<col>.json.gz`` tiles. The sidecar records per-source counts after
merge and de-duplication, the Overture release when known, and the licence and
notice obligations already stated in docs/source-rights-review.md.

It is engineering evidence, NOT legal clearance: the licence text below is
copied from the repository's own rights review, has not been independently
verified, and does not include upstream NOTICE file contents.
"""
import json
from pathlib import Path
import re

SCHEMA = 1
FILENAME = 'places-provenance.json'
KIND = 'drivemate-places-provenance'
RIGHTS_REVIEW_STATUS = 'not_independently_verified'
SOURCE_IDS = ('overture', 'osm', 'osm_addresses', 'osnames')
UNKNOWN = 'unknown'
UNAVAILABLE = 'unavailable'
OVERTURE_RELEASE = re.compile(r'\d{4}-\d{2}-\d{2}\.\d+')
REVIEW_DOC = 'docs/source-rights-review.md'

# Wording is limited to what docs/source-rights-review.md already states.
SOURCES = {
    'osm': {
        'label': 'OpenStreetMap',
        'licence': 'ODbL-1.0',
        'attribution': '© OpenStreetMap contributors',
        'obligations': [
            'Commercial reuse is possible with attribution and applicable database '
            'share-alike/source-access obligations.',
            'Preserve source fingerprints and make the derivative database/licence '
            'available where required; rendered map attribution remains necessary.',
        ],
        'evidence': ['https://www.openstreetmap.org/copyright',
                     'https://opendatacommons.org/licenses/odbl/1-0/'],
    },
    'osm_addresses': {
        'label': 'OpenStreetMap house numbers',
        'licence': 'ODbL-1.0',
        'attribution': '© OpenStreetMap contributors',
        'obligations': [
            'Same ODbL attribution and share-alike obligations as the OpenStreetMap source.',
            'Only addr:housenumber + addr:street (with addr:city/postcode where tagged) are used; '
            'nothing is invented, so coverage follows what mappers have entered.',
        ],
        'evidence': ['https://www.openstreetmap.org/copyright',
                     'https://opendatacommons.org/licenses/odbl/1-0/'],
    },
    'osnames': {
        'label': 'OS Open Names',
        'licence': 'OS OpenData terms (OGL-v3); third-party rights apply',
        'attribution': 'OS, Royal Mail and National Statistics',
        'required_notices': ['Ordnance Survey', 'Royal Mail', 'National Statistics'],
        'obligations': [
            'Preserve OS, Royal Mail and National Statistics notices and verify current '
            'product-specific third-party conditions before distribution.',
            'GB place/street/postcode data, not a complete postal-address database or NI dataset.',
        ],
        'exact_notice_text': 'not recorded; verify against the current OS OpenData terms before distribution',
        'evidence': ['https://docs.os.uk/os-downloads/products/os-open-names',
                     'https://www.ordnancesurvey.co.uk/documents/licences/os-opendata-licence.pdf'],
    },
    'overture': {
        'label': 'Overture Maps places',
        'licence': 'varies by upstream dataset',
        'attribution': 'Overture Maps and upstream contributors',
        'upstream_licences': [
            {'upstream': 'CDLA Permissive 2.0 sources', 'licence': 'CDLA-Permissive-2.0'},
            {'upstream': 'Foursquare', 'licence': 'Apache-2.0',
             'requires': 'its NOTICE and modification notice'},
            {'upstream': 'AllThePlaces', 'licence': 'CC0'},
        ],
        'obligations': [
            'Generic Overture credit is insufficient to establish all required notices '
            'for a specific release.',
            'Record the exact Overture release and retain source/licence/NOTICE '
            'information before publication.',
        ],
        'notice_file_text': 'not captured by this build',
        'evidence': ['https://docs.overturemaps.org/attribution/'],
    },
}

LIMITATIONS = [
    'Not legal clearance: licence text is copied from ' + REVIEW_DOC + ' and is not independently verified.',
    'Counts are per merged record; individual tile records carry no per-record lineage.',
    'Upstream NOTICE file contents and exact OS notice wording are not included.',
    'Each kept record is counted under the source of the entry that survived de-duplication; '
    'dropped duplicates contribute no field content to the written tiles.',
]


def checked_release(value):
    """Return a validated Overture release identifier, or 'unknown'."""
    if value is None or value == '' or value == UNKNOWN:
        return UNKNOWN
    if not isinstance(value, str) or not OVERTURE_RELEASE.fullmatch(value):
        raise ValueError('Invalid Overture release identifier')
    return value


def build(by_primary, input_counts, rejected, tile_files,
          overture_release, overture_input_present, upstream_datasets):
    """Assemble the sidecar document from merge statistics."""
    document = {
        'schema': SCHEMA,
        'kind': KIND,
        'rights_review_status': RIGHTS_REVIEW_STATUS,
        'rights_review_reference': REVIEW_DOC,
        'places_format': {
            'files': 'places-<row>_<col>.json.gz',
            'fields': ['name', 'category', 'address', 'lat', 'lon'],
            'note': 'Tile format unchanged; this sidecar adds no per-record fields.',
        },
        'total_records': sum(by_primary.values()),
        'tile_files': tile_files,
        'records_by_primary_source': {s: by_primary.get(s, 0) for s in SOURCE_IDS},
        'input_records_before_merge': {s: input_counts.get(s, 0) for s in SOURCE_IDS},
        'rejected_coordinate_records': {s: rejected.get(s, 0) for s in SOURCE_IDS},
        'overture': {
            'release': checked_release(overture_release),
            'input_present': bool(overture_input_present),
            'upstream_datasets': upstream_datasets,
            'upstream_datasets_method': (
                'Kept Overture records counted once per distinct `sources[].dataset` '
                'value in the Overture input; a record citing several datasets is '
                'counted under each, so totals can exceed the Overture record count.'),
        },
        'sources': SOURCES,
        'limitations': LIMITATIONS,
    }
    validate(document)
    return document


def _counts(value, keys=None):
    if not isinstance(value, dict):
        return False
    if keys is not None and set(value) != set(keys):
        return False
    return all(isinstance(k, str) and k and type(v) is int and v >= 0 for k, v in value.items())


def validate(document):
    """Structural check used by places.py, validate_build.py and the publisher."""
    if not isinstance(document, dict) or document.get('schema') != SCHEMA or document.get('kind') != KIND:
        raise ValueError('Unsupported places provenance schema')
    if document.get('rights_review_status') != RIGHTS_REVIEW_STATUS:
        raise ValueError('Places provenance must declare rights not independently verified')
    for key in ('total_records', 'tile_files'):
        if type(document.get(key)) is not int or document[key] < 0:
            raise ValueError('Invalid places provenance count: ' + key)
    for key in ('records_by_primary_source', 'input_records_before_merge', 'rejected_coordinate_records'):
        if not _counts(document.get(key), SOURCE_IDS):
            raise ValueError('Invalid places provenance counts: ' + key)
    primary = document['records_by_primary_source']
    if sum(primary.values()) != document['total_records']:
        raise ValueError('Places provenance counts do not add up')
    for source in SOURCE_IDS:
        if primary[source] > document['input_records_before_merge'][source]:
            raise ValueError('More merged records than input records for ' + source)
    overture = document.get('overture')
    if not isinstance(overture, dict) or not isinstance(overture.get('input_present'), bool):
        raise ValueError('Missing Overture provenance')
    checked_release(overture.get('release'))
    datasets = overture.get('upstream_datasets')
    if datasets != UNAVAILABLE and (
            not _counts(datasets) or any(v > primary['overture'] for v in datasets.values())
            or sum(datasets.values()) < primary['overture']):
        raise ValueError('Invalid Overture upstream dataset counts')
    sources = document.get('sources')
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_IDS):
        raise ValueError('Places provenance licence registry incomplete')
    for item in sources.values():
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k]
                                                 for k in ('label', 'licence', 'attribution')):
            raise ValueError('Places provenance licence entry incomplete')
    return document


def read(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))
