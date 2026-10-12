# DriveMate development register

## Regional address follow-up — 12 October 2026

Exact source CI [38215042634](https://github.com/phuk-prog/drivemate-data/actions/runs/38215042634)
passed at `4b2c979089c4731212cf2d8b0a23a100c981918a` with 339 unit tests and
five generator selftests. A source-side follow-up preserves mapped house names
when a house also has a number and uses exact numeric FTS tokens; a reordered
query for house 12 must not prefix-match house 123. Two regression tests cover
these cases; the follow-up canonical target is 341 unit tests and five generator
selftests, with unchanged-source/live-HEAD checks before upload. The unpublished Manchester experiment is regenerated and inspected
with the final exporter; no working published generation is replaced.

## Regional address milestone — 12 October 2026

| Task | Status | Acceptance and evidence |
|---|---|---|
| Add optional regional OSM address index without changing legacy places | Implemented, locally verified | SQLite B-tree/FTS4, stable OSM IDs, full mapped coordinates and source fingerprint; eleven regression tests cover indexed street/postcode/property queries, incomplete fields, approximate geometry, tampering and atomic failure recovery. `docs/regional-address-index.md` |
| Verify actual regional address data | Verified for bounded Manchester experiment | Public 2026-10-08 extract: 193,619 candidates, 191,287 usable records, 2,332 missing-field gaps, zero invalid retained geometries. Complete SQLite/record/index validation; 54/54 search smoke queries nonempty. `docs/validation/regional-addresses-manchester-20261012.json` |
| Integrate regional address package into Android and publication | Pending | Android importer/FTS4 device tests, versioned package compatibility, explicit approved publication checks and attribution remain required. Package stays unpublished; no full postal verification or vehicle entrance claim |

The real extract has 46,367 records without postcodes and 112,458 approximate
outline-average coordinates. Source/row verification is not nationwide postal,
entrance or legal driving proof. FTS4 avoids unsupported FTS5 assumptions; actual
Android package consumption remains untested. All previous working publications
remain unchanged.

Environment recovery: the first broad preflight found missing host `pyproj`,
`pmtiles` and `shapely` dependencies. Install the exact dependency versions already
pinned in `.github/workflows/source-checks.yml`, then repeat canonical preflight;
never classify missing generator imports as passing checks. Repeated canonical
preflight passes all 339 unit tests (zero failures/errors/skips) and all five
generator selftests at base `eb730932fc5e35c774c4b7ef433bf2b586da8e0b`.

## Current continuation — 11 October 2026

Live foundation HEAD was `a446223222fc31847c778b5c48355a09966f7999` when inspected.
PR #3 is now merged; earlier draft-PR and starting-state entries below are historical.
The existing development branch is reused without a main merge or publication.

| Task | Status | Measurable acceptance and evidence |
|---|---|---|
| Validate entire offline search asset | Verified | `search_integrity.py` streams every row and checks header/schema/date/credits, six fields, normalised sorted keys, supported types, finite UK-envelope coordinates, UTF-8 and gzip footer/CRC. Header-only, unsorted, truncated, invalid-coordinate and malformed fixtures must fail. The latest published asset has 2,768,087 valid records; its SHA-256 matches the manifest. Evidence: `docs/validation/offline-search-integrity-20261011.json` |
| Bind search validation into complete-build gate | Implemented, locally verified | `validate_build.py` records the search fingerprint/counts and rejects audit errors or fewer than 100,000 records for a complete UK build, alongside the existing size and exact-asset publication gates. A full UK build is not repeated merely to test source changes |

Actual source: `map-data-20261011-r38120645154-a1` manifest references the
search file in its `-extra` companion release. Downloaded 31,553,418 bytes;
SHA-256 `4a5e6b473cbfe2991622fab7ab7ed6f9855dddaa0e0ff34a3eff969a88ae06ac`.
The source build [38120645154](https://github.com/phuk-prog/drivemate-data/actions/runs/38120645154)
passed at the existing HEAD; it predates this stronger search gate.

This verifies data structure and ordering, not exact property addresses,
NI postcode completeness, human road safety or independent licence clearance.
OSNI optional feeds and unavailable live integrations remain conditional/inactive
rather than blocking independent integrity work. Mapillary was removed under
the owner-approved decision in `docs/licensing-decision-brief.md`; it must not
be reactivated merely by supplying credentials. Older rights-review entries
below describe historical findings, not a pending permission to enable Mapillary.
No stage is newly marked completed; remaining legal/data/device gates are preserved.

Local canonical preflight: 308 unit tests, zero failures/errors/skips; all five
generator selftests and source/workflow gates pass. Nine new search-integrity
regressions are included. Replaying the existing 20 Greater Manchester search
queries against the same downloaded asset produced 19 passes and one documented
misspelling limitation (`Stokport`), with zero unexpected failures. Evidence:
`docs/validation/offline-search-acceptance-20261011.json`.

Commit `8726e4d0164071c0da4b1958db596c42343d680e` passed exact-source
CI [38180431821](https://github.com/phuk-prog/drivemate-data/actions/runs/38180431821)
with 307 tests. A follow-up regression additionally handles damaged DEFLATE
blocks as a recorded validation error rather than an uncaught exception.

### Graph extract compatibility and recovery gate

`graph_archive.py` now validates the complete TAR container without writing or
extracting members. It checks nonempty regular graph tiles, unique safe paths,
the native Valhalla 3.6.3 `index.bin` records (offset, graph ID and byte length),
their one-to-one correspondence with tiles, and the decoded SHA-256/byte count.
The routing publisher performs this gate before any remote write; matching
hashes of arbitrary non-graph content cannot qualify for promotion. Existing
pointer-failure recovery and immutable-generation protections remain in place.
Validation-only builds run the same standalone checker and retain its report.

Actual evidence is the previously downloaded graph generation
`routing-uk-20261009-r37969596182-a1`, **not** a newly built or newest graph:
2,800,936,960 bytes, SHA-256
`4d88c7d2fca0b6dfc4f79cf09a128595d61f198da2b55942e123e5c7c9f729f3`,
1,341 verified index entries/tiles (17 level-0, 70 level-1, 1,254 level-2).
Report: `docs/validation/graph-extract-integrity-20261011.json`.
Six container regressions and one publisher regression cover bad containers,
unsafe/duplicate paths, forged index offsets/IDs/sizes, truncation and size/hash
mismatches. The existing promotion-recovery tests still pass.

This gate establishes extract structure; it does not decode every native tile,
prove nationwide legal routing, demonstrate Android runtime acceptance of a new
generation, or test remote recovery after process/power loss. Required device,
replay and human road-evidence gates remain outstanding. Previously published
archives remain untouched; no stage is marked completed from this source work.

### Routing manifest coherence

The publisher now rejects mixed archive prefixes, missing/reordered chunks,
noninteger or unbounded compressed sizes, unsupported source URLs, unparseable
or timezone-free timestamps and a build timestamp earlier than source retrieval.
These errors are rejected before remote writes. Four new regressions pass;
the previous recorded graph manifest and the latest immutable manifest
`routing-uk-20261011-r38120645154-a1` both pass. The latest manifest claims
decoded SHA-256 `4361e92b14d752616dc59a47ad4e9bd1ff87e9b45cc37978e619a20f9cd7a2da`
and 2,800,936,960 bytes; **its binary was not downloaded or tested in this
manifest-only check**. Actual full-container evidence above remains tied to
the explicitly older generation. Android's existing ordered-part format and
engine identity are preserved.

### Exact-graph connectivity evidence

`routing_connectivity.py` now fingerprints the tested graph before and after
the native route calls and refuses to emit a success report if graph bytes
change. Reports identify graph SHA-256, byte count, engine and schema. Three
new deterministic tests cover exact identity, same-size graph replacement and
a missing graph without invoking an actor.

Actual pyvalhalla 3.6.3 repeat: **11/11** public regional driving probes found
routes, zero investigations, on the same explicitly older graph identified
above. New bound evidence: `docs/validation/uk-connectivity-bound-20261011.json`.
This includes England, Scotland, Wales, Northern Ireland and a Wales–England
cross-border corridor; it is neither a full connected-component survey nor
proof of turn legality. Extra diagnostics remain informational, preserving
the existing six mandatory release smoke routes and Android/device gates.

### Northern Ireland gazetteer input reproducibility

The optional OSNI streets/places inputs were missing from source fingerprints.
`source_inventory.py --osni-sources work/osni` now records each observed CSV or
GeoJSON hash/size, declared OGL/LPS attribution, dataset origin and a sanitised
download URL when available. The build captures that URL only after a successful
download. Query strings/fragments are removed and credential-bearing URLs,
symlinks and ambiguous duplicate input formats are rejected. Existing schema-1
inventories without the new optional section remain readable.

Measurable acceptance: six deterministic provenance regressions pass; complete
build quality reports explicitly warn when either optional gazetteer is absent.
This inventories observed files, **not** whether the search reader accepted
their rows. Real OSNI files were not retrieved in this work; prior HTTP 403 and
field-schema/coverage limitations remain recorded. No postcode dataset was added,
no permissions were inferred from a hash, and no mandatory feed was introduced.

### Exact-source verification ledger (11 October)

| Verified commit | Task | Local canonical tests | Exact-source GitHub evidence |
|---|---|---:|---|
| `8726e4d0164071c0da4b1958db596c42343d680e` | Complete offline search audit/gate | 307 | [38180431821](https://github.com/phuk-prog/drivemate-data/actions/runs/38180431821), passed |
| `34de771d04eebdc5d4882e66e01a5013bdf089a6` | Invalid DEFLATE regression | 308 | [38180494753](https://github.com/phuk-prog/drivemate-data/actions/runs/38180494753), passed |
| `5daa580f03bd6c3e7d3e7d17931983c5abbaf85a` | Complete graph extract/index gate | 315 | [38180854084](https://github.com/phuk-prog/drivemate-data/actions/runs/38180854084), passed |
| `c4a960d528cc3559caf9ce45891da5e07b3b77be` | Routing manifest coherence | 319 | [38180999048](https://github.com/phuk-prog/drivemate-data/actions/runs/38180999048), passed |
| `a45f4b9dabbdec58513cf6e550b2c75131e3221e` | Exact-graph diagnostic identity | 322 | [38181141719](https://github.com/phuk-prog/drivemate-data/actions/runs/38181141719), passed |
| `bb1030ab62e14fe0c08c541c0efb25713214c627` | Optional OSNI observed-input inventory | 328 | [38181365217](https://github.com/phuk-prog/drivemate-data/actions/runs/38181365217), passed |

Each local canonical run had zero failures, errors and skips, and all five
generator selftests passed. Foundation pushes started only serialized source
validation. No production pointer, map publication, full UK build or main merge
was initiated by these changes.

Outstanding gates remain explicit: Android runtime acceptance/performance of
the relevant real UK generation; remote/power-loss publication recovery beyond
the existing fault-injection regressions; actual optional NI input field/coverage
verification; LPS permission before distributing restricted NI postcode data;
human evidence for precise lane transitions/legal restrictions; and required
application replay/device/robot checks for any APK. Continue independently with
source and package preparations while conditional features stay inactive.

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

**Whole-UK exporter stress test (local, unpublished):** all 207 archives
(base + 206 regions) were exported from the verified UK archive in 18 s and
every one passed `verify_pmtiles.py` (0 failures, 164 s total). All 957,592
source tiles were accounted for exactly once, with every payload compared
byte-for-byte. The largest real package is 143,577,563 bytes. This tests the
shared exporter only. It is not a ledger entry: ledger completions still
require a GitHub workflow run once bulk expansion is approved.

## Full UK validation-only build — result recorded (10 October 2026)

The nonpublishing UK build listed above as "result pending"
([run 38027913632](https://github.com/phuk-prog/drivemate-data/actions/runs/38027913632),
commit `3e8c7a4`) **succeeded** in 57 minutes. Both publishers were skipped as
designed. Compact evidence: `docs/validation/uk-validation-build-20261010.json`
(the full artifacts expire on 13 October).

- Map 1,639,454,841 bytes; 217 lane squares (593,122 ways); **214 speed-limit
  squares (1,333,420 ways)**; **222 road-information squares** (409,835
  warnings and landmarks); 903 places archives (4,560,095 records, 0 invalid);
  18,930 cameras / level crossings; **12 charge and emission zones**; **offline
  search file** with 2,768,087 records (31.6 MB). Whole-build quality gate passed.
- All four nations have lanes, limits, road information and places in the
  sample probes. Northern Ireland postcode and street search is still
  missing (OS Open Names covers Great Britain only).
- Routing graph built from the same OSM extract (SHA-256 `7857cd61…1424`),
  and all 11 sampled UK journeys were found.
- Manchester restriction audit: 739 turn-restriction relations sampled (656 node-via,
  83 way-via), **108 flagged for human review** (for example missing roles and
  possible one-way orientation conflicts). These are flags to check, not
  proof of errors, and no turns were invented.
- Mapillary sources were omitted, pending the rights review.

This closes "Validate actual complete UK map" for generated-data quality.
It makes **no licence decision**. These richer layers (limits, road
information, zones, search) are not yet in the published release, so phones
still lack them until a publication is approved.

## Second batch — 10 October 2026 (merged to `codex/architecture-foundation` with approval)

The user approved merging the Claude branches into `codex/architecture-foundation`
(both were fast-forwards). Exact-source CI then ran on the development branch.

| Item | Status | Evidence |
|---|---|---|
| Data CI on merged heads | Verified | source checks green on every pushed commit; regional pilot re-run green with the reproducible exporter |
| Android CI on merged head `dd5b60f` | Verified | source/lint/JVM plus emulator: native offline routing, device tests, navigation robot, no crashes |
| Real-data fixture cutter (`pmtiles_fixture.py`) | Implemented, tested | 3 tests; central Manchester fixture 3.0 MB, byte-for-byte tiles |
| Android real Manchester rendering device test | **Passed on emulator** | Deansgate, Peter Street, Oxford Street and Mosley Street; buildings; house numbers; main roads; base/detail zoom split. Two follow-up test-harness fixes: main-thread exceptions and waiting for the first native frame |
| Regional publication path (`region_publication.py`, publisher gate, build step) | Implemented, real-data validated; **off** until `PUBLISH_REGIONAL_MAPS=true` | 207/207 real archives staged and validated |
| Android `RegionalMaps` controller (published manifest only, cross-checked hashes) | Implemented, JVM-tested | No UI or renderer switch yet |
| Places provenance sidecar | Implemented (agent), reviewed, merged | 142 data tests; Overture release now pinned and recorded |
| Northern Ireland search sources | Researched | OSNI gazetteers usable under OGL; ONSPD BT rows need written LPS permission |

Remaining before regional activation: the live-map regional renderer switch
plus its on-device check, a user decision on licensing (then set
`PUBLISH_REGIONAL_MAPS`), and enabling `docs/regional-batch-request.json`.
