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
No map-generation performance result is claimed yet. Tilemaker v3.2.0 publishes
no prebuilt release assets, so a runnable comparison requires a source build or
verified distribution package. Absence of a convenient binary is not evidence
that it performs worse.

Provisional decision: retain MapLibre and Valhalla while completing Android and
shared replay evaluation. Keep Ferrostar as a measurable candidate. No full
rewrite is justified by the evidence collected so far.
