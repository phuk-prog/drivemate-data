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
| Verify source rights and lineage | Blocked | `source_inventory.py` records declarations, not clearance; historical release lineage is absent. Current code fingerprints Planetiler ancillary archives, but this is not rights clearance. Overture upstream terms and Mapillary derived observations require review; README claims corrected; primary-source findings recorded in `docs/source-rights-review.md` |
| Validate actual complete UK map | In progress | All 999 current manifest assets downloaded and SHA/size verified. Four z14 map tiles decode with roads/buildings/house numbers. Full 780-place-archive audit reports six outside-envelope archives; current release lacks limits/roadinfo/search. See `docs/validation/` |
| Validate routing graph and Android consumers | Testing | Current graph compressed and decoded SHA/size verified (2,800,936,960 bytes); four repeated benchmark routes and 11 extra UK journeys pass on pyvalhalla 3.6.3. PMTiles uses existing OpenMapTiles layers; five-field places preserved. Actual UK graph on Android remains unverified |
| Coverage and search | Implemented | `coverage_audit.py`: four core and 19 additional probes plus place archive scan. `search_offline.py`: GB Open Names only; NI postcodes and individual postal addresses incomplete |
| Recovery | Implemented | Existing publication corruption and pointer recovery regressions pass locally; remote recovery and power-loss limitations still require evidence |
| Commit and verify exact-source CI | Verified | `50906eb3e82d42b938425f6f1f83aa3a319718b8`, exact source CI https://github.com/phuk-prog/drivemate-data/actions/runs/38027404597 passed |

## Known gaps and next action

Next verify exact-SHA CI, complete source licensing/ancillary inventory and safe full UK validation before progressing to Stage 2. Current local environment has 9.7 GiB RAM and about 30 GiB free disk; the existing map workflow requests a 12 GiB Java heap. Do not launch a full local map build without sizing its dependencies and workspace.

After local changes, all 85 unit tests pass (83 existing plus two workflow regressions). README now explicitly distinguishes preliminary declarations from legal clearance and imagery terms from derivative-data permissions. Canonical preflight now passes; generated-data checks remain outstanding.

No stage is marked completed on source tests alone. No production publication, release APK publication, main merge or budget expenditure occurred. Android consumer protection is now being tested separately on its existing development branch.

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

## Current full-payload source verification

- Data commit `e0b8216131d1dedc793877be326eb752085f2c4f` passed exact-source CI https://github.com/phuk-prog/drivemate-data/actions/runs/38029092446: 98 unit tests and five generator selftests.
- The complete PMTiles audit covers 252,138 directory entries and 221,293 physical contents, not unique byte hashes. Sixteen physical blocks have identical bytes; this is permitted deduplication behavior, not evidence of corruption.
- Android commit `4c4f8b9c55be31973f78f32c8bd9f30106edfbb0`: canonical preflight passed (293 JVM tests, zero failures/errors/skips, tooling gates, lint and robot test APK assembly). Exact-source CI https://github.com/phuk-prog/DriveMate/actions/runs/38029477016 is queued; device/robot results remain pending. Private replay unavailable; release readiness remains false. These do not establish nationwide driving legality or physical-device performance.


## Approved regional packaging architecture — 10 October 2026

User approved choosing optimal section sizes and implementing. Decision:
low-zoom (z0–9) nationwide base + Web Mercator z8-parent detail packages
(z10–14) subdivided to z9/z10 in dense areas. Maximum detailed archive size
200,000,000 bytes as a testable initial bound. Local Manchester z8/126/82
pilot first; source/consumer compatibility preserved. **Stage 6 packaging
foundation has been brought forward without claiming Stage 1 complete.**
See `docs/regional-packaging.md` and `scripts/region_pmtiles.py`.
Only synthetic source CI and unpublished prototype are authorised until
full UK validation-only build resolves; no new GitHub large map build
or production map release should be started by this change.


## Manchester real regional pilot — 10 October 2026

The user approved the base-z0–9 plus adaptive detailed-z10–14 approach.
Extended exporter now checks all tile identities/payloads, not a first/last
sample. Regression tests include a middle tile and retained nationwide z9
tiles when child regions split. A separate nonpublishing UK pilot workflow
(`.github/workflows/regional-pilot.yml`) shares the `map-data` concurrency
group with the active full UK generation, verifies the historical PMTiles
SHA-256 and writes audit artifacts only (no raw map files, new release,
download pointer or Android activation). The real pilot remains *testing*
until that workflow has completed successfully and user-visible renderer
compatibility has also been validated. See `docs/regional-packaging.md`.

## Evidence checkpoint: first Manchester regional export

The real nonpublishing UK pilot succeeded at data commit `7cd5ee2`:
1,063 base tiles in 18.19 MB plus 5,456 Manchester detail tiles in
116.26 MB; all 6,519 tiles matched source, archives fully decoded and
validated. See [run 38031100907](https://github.com/phuk-prog/drivemate-data/actions/runs/38031100907)
and `docs/regional-packaging.md`. This marks *regional export pilot
verified*, NOT Android rendering/integration or Stage 1 complete.

The Android development branch now contains a read-only region package
selector at commit `6d92e843e2ad80995f967ae621a60d89276ccfe4`;
exact-source CI and device checks must be confirmed before claiming it
verified. Preserve production map/download formats until then.


## Approved deployment order — 10 October 2026 (Manchester first)

**User approval:** implement all reusable UK navigation/mapping code and
shared tests first; use real Greater Manchester for full end-to-end field
and emulator verification; after the pilot and licensing gates have passed,
expand the UK map section-by-section using scheduled nonoverlapping runs.
Do not interpret broad code implementation as proof that missing legal
restrictions, camera data, lane markings or house numbers are complete.

**Prepared:** the regional expansion queue and nonpublishing workflow live
at `scripts/region_batch_queue.py` and `.github/workflows/regional-batch.yml`,
with immutable generation-scoped ledger in
`docs/regional-batch-ledger.json`. Run requests are disabled in
`docs/regional-batch-request.json` until the required code and Manchester
acceptance gates are verified. The queue seeds the successful Manchester
source-archive pilot from run `38031100907`, then orders the remaining
z8 root areas outward from Manchester, keeping subdivided packages together.
Every subsequent run checks hashes, archive structure, tile identities,
package byte limits and complete output evidence before committing success.
It never publishes a raw package or activates it in an app.

**Exact-source evidence:** data CI run
https://github.com/phuk-prog/drivemate-data/actions/runs/38034869594
passed with 112 unit/regression tests. Android's latest earlier
regional-rendering test workflow run
https://github.com/phuk-prog/DriveMate/actions/runs/38034154443
passed on commit `d4957a7`; synthetic emulator geometry does not
establish real Manchester feature completeness or data rights.

**Scheduled controller:** one daily ChatGPT DriveMate UK Expansion task
checks/continues the existing repositories sequentially. GitHub Actions
`schedule` executes only workflows on the repository default branch,
so this developer-branch batch runner is triggered by an expressly enabled
new sequence committed to `docs/regional-batch-request.json` (or a
manual dispatch when available), not an ungrounded claim of native GitHub
cron availability. Current bulk expansion is deliberately paused, and
no map content/Android production APK/main branch was changed.

Next milestones before enabling regional bulk jobs:
1. Implement and source-test remaining compatible reusable software modules.
2. Demonstrate real-area Manchester MapLibre rendering and UK route legality,
   address/POI source integrity, seam and offline recovery in the Android app.
3. Review distribution/source rights (especially Overture lineage, imagery
   and OS obligations), and decide safe permitted publication/attribution.
4. Re-check CI, privacy, performance, output formats and budgets, then
   explicitly change the batch request to enabled with sequence 1.
5. Run one z8-area validation at a time, persisting proofs before resuming.


## Regional download batch — 10 October 2026 (Claude session)

Development continued on `claude/drivemate-uk-navigation-9oysko` in both
repositories, branched from the current `codex/architecture-foundation`
heads (data `c3ee41e`, Android `d4957a7`); nothing was merged to
`codex/architecture-foundation` or `main`.

| Item | Status | Evidence |
|---|---|---|
| Companion squares per regional package (`region_companions.py`) | Implemented, verified locally on real data | Manchester: 12 lane + 28 places squares from real release inventory |
| Multi-region budgeted batch requests with per-region checkpoint/resume | Implemented, source-tested | `test_region_batch_queue.py` (3 new), `test_regional_batch_workflow.py` |
| Reproducible regional PMTiles exports | Fixed, verified on real Manchester | Two exports byte-identical; full verifier passes |
| Whole-UK partition on real archive | Verified (planning only) | 206 packages, none over 200 MB, no subdivision; `docs/validation/uk-regional-plan-20261010.json` |
| Android regional manifest parser / planner / resumable verified downloader | Implemented, JVM-tested | Android preflight: 326 JVM tests, lint, robot assembly; `RegionalMapDownloadTest` |
| Bulk regional expansion | **Held (disabled)** | Gates below still open |

Unchanged gates before setting `docs/regional-batch-request.json` to enabled:
real Manchester on-device rendering/navigation acceptance, source-rights
decisions (Overture lineage, Mapillary caches, OS notices) and exact-source CI
on the development branch. The "DriveMate UK Expansion" scheduled controller is
not visible among this account's Claude routines (it is described above as a
ChatGPT task); no duplicate automation was created.

Data preflight on this branch: 125 unit tests and five selftests pass.
