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
