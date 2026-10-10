# DriveMate development register

Updated 2026-10-10. Budget: £20 one-off maximum; no spending or paid services enabled.
Development stays on `codex/architecture-foundation`, existing draft PR #3 in each repository.

## Verified starting state

- Data HEAD: `e5fba6ba1c91b9dc5b884b2a7e8083251d47326b`; main `0dfd3354d7154d44ada7b7e9d58b9b117d30253a`.
- Android HEAD: `06763db2509a47c15a0b09b944bd0db94daa192e`; main `f185bca445aa4887bd40bbbb29426595abe6a199`.
- Data source CI: https://github.com/phuk-prog/drivemate-data/actions/runs/38000326855 succeeded on exact data HEAD.
- Initial work used a connector-retrieved snapshot while the proxy was unreachable. Network access recovered on 2026-10-10; both repositories now have real checkouts. Pinned dependencies installed in `/workspace/venv`. Reviewed changes transferred to the unchanged live data HEAD.
- Existing graph publication and six desktop smoke journeys are described in PR #3 and `docs/integration-reconciliation.md`; not independently rerun here and not nationwide legal ground truth.

## Stages and measurable acceptance

| Stage | Improvements | Status | Acceptance / dependencies |
|---|---|---|---|
| 1 Foundation | 14, 15 foundation | In progress | Canonical preflight, actual complete UK asset validation, graph compatibility, four-nation coverage, recovery proof, source rights review; no critical defects |
| 2 Roads and lanes | 1, 4, 6, 7, 8, 9 | Pending | Stage 1 completed; representative UK road, junction, legal restriction and lane regressions pass; unknowns preserved |
| 3 Geography | 2, 3, 5, 11 | Pending | Stage 2 completed; licensed address/building/terrain datasets verified, GB/NI gaps disclosed, offline search and regional packages tested |
| 4 Imagery | 12 | Pending | Stage 3 completed; evidence records include location, before/after, source, date, confidence and human verification; uncertain legal changes blocked |
| 5 Live information | 10 | Pending | Stage 4 completed; permitted free feeds, attribution, expiry and offline/unavailable behavior tested |
| 6 Delivery | 13, 15 | Pending | Stage 5 completed; coherent versioned map/search/graph/lane/terrain packages, resumable downloads, rollback, Android compatibility/performance and required release tests pass |

## Stage 1 task controller

| Task | Status | Existing references / acceptance / evidence |
|---|---|---|
| Inspect both live branches and PRs | Verified | GitHub PR metadata and recursive trees read; historical data HEAD unchanged; no competing branches or PRs |
| Reuse existing safeguards | Implemented | `publish_map_data.py`, `publish_routing_data.py`, `publication_consistency.py`: immutable assets, hash checks, recovery regressions; preserve them |
| Run source/unit tests | Verified | Canonical preflight passes at base `e5fba6b`: 85 unit tests, zero failures/errors/skips, all five generator selftests, source scan and ancestor/workflow gates pass |
| Nonpublishing full-build mode | Verified | Manual `validate_only` defaults true and gates both publishers; local regression passes. Source CI passed at `50906eb` (run 38027404597); real build pending |
| Preserve house numbers | Verified | Oversized PMTiles now stops instead of excluding housenumber layer; source CI passed at `50906eb`. Regional packaging still pending, no consumer format changed |
| Verify source rights and lineage | Blocked | `source_inventory.py` records declarations, not clearance; optional origins and Planetiler ancillary sources absent. Overture upstream terms and Mapillary derived observations require review; README claims corrected; primary-source findings recorded in `docs/source-rights-review.md` |
| Validate actual complete UK map | In progress | All 999 current manifest assets downloaded and SHA/size verified. Four z14 map tiles decode with roads/buildings/house numbers. Full 780-place-archive audit reports six outside-envelope archives; current release lacks limits/roadinfo/search. See `docs/validation/` |
| Validate routing graph and Android consumers | Testing | Current graph compressed and decoded SHA/size verified (2,800,936,960 bytes); four repeated benchmark routes and 11 extra UK journeys pass on pyvalhalla 3.6.3. PMTiles uses existing OpenMapTiles layers; five-field places preserved. Actual UK graph on Android remains unverified |
| Coverage and search | Implemented | `coverage_audit.py`: four core and 19 additional probes plus place archive scan. `search_offline.py`: GB Open Names only; NI postcodes and individual postal addresses incomplete |
| Recovery | Implemented | Existing publication corruption and pointer recovery regressions pass locally; remote recovery and power-loss limitations still require evidence |
| Commit and verify exact-source CI | Verified | `50906eb3e82d42b938425f6f1f83aa3a319718b8`, exact source CI https://github.com/phuk-prog/drivemate-data/actions/runs/38027404597 passed |

## Known gaps and next action

Next verify exact-SHA CI, complete source licensing/ancillary inventory and safe full UK validation before progressing to Stage 2. Current local environment has 9.7 GiB RAM and about 30 GiB free disk; the existing map workflow requests a 12 GiB Java heap. Do not launch a full local map build without sizing its dependencies and workspace.

After local changes, all 85 unit tests pass (83 existing plus two workflow regressions). README now explicitly distinguishes preliminary declarations from legal clearance and imagery terms from derivative-data permissions. Canonical preflight now passes; generated-data checks remain outstanding.

No stage is marked completed on source tests alone. No production publication, Android changes, APK, main merge or budget expenditure occurred in this session.

## Continuing Stage 1 — 10 October 2026

- UK places coordinate filter: Implemented, Testing. Reject and count non-finite/out-of-envelope coordinates before indexing; regression inputs cover the six actual failing tile regions and valid four-nation records with house numbers retained. A UK envelope is not a national boundary.
- Planetiler ancillary inventory: Implemented, Testing. Fingerprint three required archives and optional Wikidata translations; missing core source and tampering regressions must pass. Licence review remains separate.
- Full-build evidence: Implemented, Testing. Retain lightweight map/graph diagnostics for three days, including failure paths. Preflight, Java/Osmium and runner capacity checked before costly map processing. No full UK artifacts uploaded by validation-only mode.
- Routing CLI directory dependency: Implemented, Verified locally against the actual UK graph. Temporary tile directory removes caller setup requirement; 11/11 probes pass.

Full generated-data and independent legal/road correctness remain outstanding; stages 2–6 retain dependency holds.

Current correction preflight target: 91 unit tests and five generator selftests. Validation-only full builds omit Mapillary observation acquisition/caches; source inventory records those sources absent. See `docs/source-rights-review.md` and `docs/validation/README.md` for exact inputs, findings and reproduction.

## Full archive verification and consumer protection

- `3e8c7a49848e03ab5f812afd9e61bd4920e21773` passed source CI https://github.com/phuk-prog/drivemate-data/actions/runs/38027879059 (91 tests and five selftests).
- Nonpublishing UK build https://github.com/phuk-prog/drivemate-data/actions/runs/38027913632 started at that exact commit with `components=all`, `validate_only=true`; dependencies and runner capacity passed. Production publishers are gated off. Result pending; this run predates the added full-payload gate, whose actual published-archive evidence is recorded separately.
- Repeatable complete PMTiles verifier: Implemented, Verified locally against the current map. All 957,592 addresses, 221,293 physical contents and 23 city road-layer samples pass format checks. New corruption regressions cover truncated gzip, invalid MVT tag indices, forged counts and a tiny archive claiming UK coverage. Payload reports are bound to the final map fingerprint.
- Android offline map replacement: Testing. Consumer inspection found size/header-only replacement in `MapPack.kt`; checksum-before-rename protection is being tested on the existing Android branch without activating unfinished data. Local SDK/JDK setup and trusted session CA configuration were required; no TLS bypass or native dependency change. Existing graph protections remain unchanged.
- Local OS Open Names binary download: Blocked by HTTP 403 on `omseprd1stdstordownload.blob.core.windows.net`; API metadata is available. Do not call this archive retrieved or verified locally. GitHub-runner retrieval remains to be observed.
