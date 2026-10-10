# Offline search index experiment

This is an additive architecture prototype. The Android app and weekly publisher do not consume the index yet. The existing pipeline and fallback are unchanged.

`scripts/search_index.py` converts the legacy OS Open Names TSV gzip from data PR #1 into a SQLite B-tree prefix index. It streams input, validates header/date, sorted ASCII keys, types, coordinates, row/line/decompression bounds and gzip CRC, then checks SQLite integrity before replacing the destination through a same-directory rename. Failed/truncated/corrupt input leaves the previous output intact. Source header attribution (including OS/Royal Mail/National Statistics where supplied) and build date remain in metadata. Postcodes remain approximate postcode areas; other records are named features. No property-address or accessible-entrance coverage is invented.

This single-file prototype does not retain a previous installed generation after successful replacement, implement a full package manager, authenticate a publisher, or guarantee directory durability across power loss. Those belong to the versioned package installer before app adoption. File-format metadata is not independent verification of upstream licence or provenance.

Build from an existing source file:

```sh
python3 scripts/search_index.py /path/to/search-offline-uk.tsv.gz /path/to/search.sqlite
python3 -m unittest discover -s tests -v
```

Reproduce the desktop experiments:

```sh
python3 scripts/benchmark_search_index.py --rows 250000 --repeats 5 --output /tmp/search-250k.json
python3 scripts/benchmark_search_index.py --rows 1000000 --repeats 5 --output /tmp/search-1m.json
```

The generated records use synthetic names and coordinates at (0,0), with no real driving traces. The gzip scan is a Python model of the current Kotlin candidate scan, not execution of the Android app. Both algorithms must return identical candidates for early/middle/late, missing and broad queries before timing is reported. Ranking and proximity selection are outside the experiment. Warm OS cache, desktop SQLite/Python and synthetic compression materially limit extrapolation.

At one million rows the final late-query medians were 473.188 ms for gzip scanning and 0.014 ms for indexed retrieval, with equal candidates. Index size was 102,551,552 bytes versus 5,034,457 gzip bytes. SQLite is a candidate for reducing late-query work, with a substantial expanded-storage cost. Validate a compressed index transfer, Android opening/query cost, cancellation, actual data, ranking, battery and regional package recovery before choosing it for production. Raw measurements and implementation hashes are in [250k report](benchmarks/search-250k.json) and [1m report](benchmarks/search-1m.json).

Existing publisher tests plus three new index tests pass (14 total). New tests cover the original format's blank postcode name, prefix/index access, approximate precision, invalid/unsorted/empty input, decompression corruption and preservation of a previous database. These are desktop tests; no Android result is claimed.
