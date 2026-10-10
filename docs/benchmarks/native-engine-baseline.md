# Native engine experiments

DriveMate's existing Greater Manchester graph was decompressed and SHA-256
verified before testing with pyvalhalla 3.6.3. Four public-landmark requests
generated usable, deterministic route summaries over seven repetitions each.
Warm median request times on this Linux workspace were 146–275 ms. Peak process
RSS was 134,448 KiB, including Python and the native engine. The archive unpacked
to 99,502,080 bytes. Detailed requests, timings and environment are recorded in
`valhalla-desktop.json`; reproduce using `scripts/benchmark_offline_routes.py`.

This experiment uses local tiles and does not require an online routing service.
It does not disable host networking, establish legal ground truth, measure
Android latency/battery, or prove Android JNI works. Those require separate
Android tests and validated road fixtures.

Ferrostar 0.57.0 source at
`4e2d7f647952c0a4060efd584e6edfc6148092b9` compiled locally and passed all 110
upstream library tests with Rust 1.99.0. Command:
`cargo test -p ferrostar --locked --lib` in its `common` directory. The test run
finished in 1.28 seconds excluding compilation. This is upstream correctness
evidence, not a comparative DriveMate route-following benchmark or a reason to
replace the existing navigation controller. Integration needs shared DriveMate
replays, parser equivalence and Android ABI/size/16 KB alignment evidence.

Planetiler 0.10.1's official jar was downloaded and verified against the release
asset SHA-256 `5e5e7d8c4fc89b4573cc9109d0a543c3c2c798b2bcde7c3dcd2214031ee59c29`.
It reports upstream build `9c4f2c14680356aa7bb9e1ad9ab164c4ebe0fa55` and starts
under Java 21. A Geofabrik Isle of Wight OSM input was downloaded with SHA-256
`de5be3939f6b52b9919eb05b7537ca58544bd9f3852d0f60ea9ba3d462fb52a9`.
The road-only regional profile in `scripts/benchmark-road-profile.yml` built
279 identical decompressed tiles in PMTiles and MBTiles over three alternating
trials each. Median build times were 7.307 and 7.236 seconds respectively;
this difference is too small to establish a speed advantage on a shared host.
PMTiles was 567,709 bytes versus MBTiles 651,264 bytes (12.8% smaller). The
archive coordinates and every decompressed tile payload matched. Reproduce with
`scripts/benchmark_vector_formats.py`; detailed commands/hashes/RSS are in
`vector-formats.json`. This is not the production OpenMapTiles profile or proof
of whole-UK capacity, road legality or Android rendering equivalence.

An initial 768 MiB heap trial failed with `OutOfMemoryError` after 14.75 seconds
and 736,912 KiB peak RSS. The successful trials used a 2 GiB heap and two threads.
This minimum-memory failure matters: a small compressed OSM input does not imply
a small builder memory requirement. Tilemaker v3.2.0 publishes no prebuilt release
assets; its source-build comparison remains outstanding. Absence of a convenient
binary is not evidence that it performs worse. The production Planetiler download
is now pinned to the verified 0.10.1 release and checked before execution.

Ferrostar's default OSRM parser rejected all 26 shared DriveMate GeoJSON
responses. Converting only route/step geometry to polyline6 made all 26 accepted
with the same route counts. Reproduce using `scripts/benchmark_ferrostar.py`
and the pinned upstream checkout after running its locked library tests.
`ferrostar-compatibility.json` records source/input hashes and per-fixture
parser results; the adjacent Cargo lock records resolved dependencies. Timings
use an unoptimized debug build and are not compared with Android performance.
The encoding adapter resolves a concrete integration requirement; guidance,
lane-confidence rules, legal restrictions and replay equivalence still need tests.

Android integration at `cebd58f5a41a1efecda38bf4a0e402415390c0c4` passed
[CI 37962999005](https://github.com/phuk-prog/DriveMate/actions/runs/37962999005):
258 JVM tests, 13 Android instrumentation tests including direct native offline
route/recalculation, navigation robot and no crashes. The final APK job was
intentionally skipped. All packaged arm64/x86_64 native ELF load segments and
the robot APK passed static 16 KB alignment checks locally; 16 KB device
execution, physical phone/Bluetooth and Android Auto host behaviour remain unverified.

The emulator baseline recorded cold activity launch 2,658 ms and, after its
synthetic drive, 385,906 KiB PSS / 524,128 KiB RSS. Its rendering sample had
89 frames, all classified janky, p50 250 ms and p95 500 ms. These are material
performance observations, not a physical-device result or proof of an efficient
renderer. They require investigation with a controlled rendering benchmark.
Synthetic GPS-noise tests passed six scenarios; the delayed-fix scenario had
p95 longitudinal error 52.94 m. The replay report identified 327 manoeuvres
without lane data, so successful tests do not imply complete lane coverage.

Provisional decision: retain MapLibre, Valhalla, Planetiler and PMTiles while
completing performance, full-profile and shared guidance evaluation. Keep
Ferrostar as a measurable candidate. No full rewrite is justified by the
evidence collected so far.

### UK graph publication recovery (2026-10-09)

The `routing-uk` release was absent when inspected. Manchester routing remains the
only downloaded native graph verified in the application; UK capability is not yet
established. The previous workflow verified uploaded sizes alone and could hide
failed graph/admin builders behind `tail` without `pipefail`.

The replacement publisher verifies gzip CRC, bounded decoded size, final SHA-256,
per-piece GitHub SHA-256 and immutable generation inventories before changing the
backward-compatible pointer. A failed replacement restores and verifies the prior
pointer. GitHub replacement is recoverable, not atomic. Previous chunks and immutable
manifests remain available; capacity exhaustion stops publication rather than deleting
older graphs. Source PBF fingerprint, retrieval date, licence and build identity are
recorded. Six journey smoke checks still do not prove geographical completeness,
correct turn restrictions or legal routing.

Graph builders now fail on pipeline errors and read the full OSM source. The previous
highway-class filter could omit explicitly vehicle-accessible ways. Valhalla owns access
interpretation; building every class may increase disk and memory needs. A routing-only
manual workflow input permits a serial UK trial without rebuilding unrelated map data.
The official extract script is checksum pinned. The pyvalhalla wheel remains version
pinned rather than digest pinned. No UK build or publication is claimed by source tests.

### First UK graph and matched regional trials

The routing-only [build 37969596182](https://github.com/phuk-prog/drivemate-data/actions/runs/37969596182)
at `2eb066d54695d3dc575bd07c7b1eff8eac752f21` completed successfully. The map
job was skipped. It published immutable generation
`routing-uk-20261009-r37969596182-a1` and its verified compatibility pointer.
Download size is 1,016,384,059 bytes; decoded graph size is 2,800,936,960 bytes.
The downloaded chunk was independently hashed in this workspace and matched
GitHub's asset digest and manifest. Full gzip decoding, size and graph SHA-256
were verified again before benchmarking. The graph and source fingerprints,
retrieval date and ODbL attribution are recorded in [uk-graph-baseline.json](uk-graph-baseline.json).

All six desktop native workflow journeys passed: Stockport–Liverpool 66.0 km,
Stockport–Sheffield 58.2 km, Manchester–Wrexham 91.1 km,
Carlisle–Gretna 15.9 km, London–Cardiff 241.2 km and Belfast–Lisburn 16.3 km.
These smoke checks establish successful requests at those endpoints, not every
road, legal restriction, conditional access, lane or Android JNI behavior.

The reusable routing benchmark now accepts an explicit published graph manifest,
while its default remains the exact bundled Manchester graph. Both hashes and
decoded sizes are mandatory; an arbitrary bigger graph cannot weaken the bounds.
Four alternating fresh-process trials used identical four-landmark requests,
seven repeats each, on Python 3.12 / pyvalhalla 3.6.3. Route summaries were
deterministic per graph. Three cases had identical regional/UK distance and time
summaries; Bolton–Stockport differed by five metres. This is not legal ground truth.

| Metric (median across four trials) | Manchester graph | UK graph |
| --- | ---: | ---: |
| Decoded bytes | 99,502,080 | 2,800,936,960 |
| Unpack + SHA verification | 805 ms | 22,808 ms |
| Actor initialization | 20.9 ms | 29.2 ms |
| Process peak RSS, including Python | 134,016 KiB | 149,678 KiB |
| Manchester–Stockport warm median | 57.4 ms | 71.0 ms |
| Stockport–Manchester warm median | 71.9 ms | 96.8 ms |
| Airport–Manchester warm median | 42.1 ms | 48.7 ms |
| Bolton–Stockport warm median | 74.0 ms | 75.9 ms |

The larger graph did not require loading its entire byte size into process RSS.
Absolute timings varied: the first UK actor initialization was 165 ms, and one
UK reverse-route warm median reached 175 ms. CPU affinity, frequency, temperature
and OS caches were not controlled. The full ranges/order and benchmark script
fingerprint are in [uk-regional-comparison.json](uk-regional-comparison.json).
These are desktop baselines, not Android performance, memory, battery or guidance
measurements. They support retaining the native engine provisionally; Android UK
route/recalculation and recovery must still be tested.

Reproduce after downloading and checking the immutable generation's chunk and
manifest:

```sh
python scripts/benchmark_offline_routes.py uk.tilepack result.json \
  --graph-manifest routing-uk.json --repeats 7
```
