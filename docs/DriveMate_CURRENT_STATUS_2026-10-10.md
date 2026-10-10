# DriveMate — verified cross-AI project status

**Snapshot date:** 10 October 2026 (UK). **Type:** Factual, point-in-time handoff, not an instruction set, a release approval, or a claim that untested functionality works. Information was checked against live GitHub repository/Actions data and the current ChatGPT scheduled-task record. All GitHub links and exact commit hashes are supplied to allow independent rechecking. Later changes supersede this snapshot.

## 1. Project currently being developed

DriveMate is an Android driving/navigation app for the United Kingdom. The user-established development approach is to implement shared navigation and map software once, validate it using real Greater Manchester data and Android tests, and then expand detailed geographical mapping across the UK using a controlled regional workflow. Offline and online navigation, legal turn restrictions, accurate junctions, lane information, addresses, road features, speed information, regional map downloads and reasonable resource usage are parts of the wider existing project. This describes the project's recorded scope, **not** a statement that every feature is finished.

## 2. Repositories and verified branch positions

| Item | Verified position at snapshot |
|---|---|
| Android repository | https://github.com/phuk-prog/DriveMate |
| Android `main` | `577b72413afa2039730f704c550194fff442a1fc` |
| Android `codex/architecture-foundation` | `577b72413afa2039730f704c550194fff442a1fc` |
| Android PR #3 | **Merged and closed** at 2026-10-10 15:17:33 UTC; https://github.com/phuk-prog/DriveMate/pull/3 |
| Map-data repository | https://github.com/phuk-prog/drivemate-data |
| Map-data `main` | `0dfd3354d7154d44ada7b7e9d58b9b117d30253a` |
| Map-data `codex/architecture-foundation` | `6000b6b53881b66a12b597def2072f8c2a9207c1` |
| Map-data PR #3 | **Open, draft, not merged**; https://github.com/phuk-prog/drivemate-data/pull/3 |

The Android merge makes earlier instructions to keep *both* PRs unmerged out of date. The map-data development branch remains distinct from map-data `main`.

## 3. Last verified Android result and actual distribution status

- The Android **main-branch** GitHub Actions run at commit `577b7241` **passed**: https://github.com/phuk-prog/DriveMate/actions/runs/38063012417 . Its source/unit/lint, Android emulator/navigation robot and final APK jobs each reported success.
- The run produced a GitHub Actions artifact named `DriveMate-apk`, reported archive size **59,852,626 bytes**. Other build/test artifacts also exist.
- The GitHub **Releases** API returned **no Android releases** at the time checked. Therefore a successful downloadable workflow artifact is verified; an Android public GitHub release or Play Store publication is **not** established.
- The Android code includes real Manchester regional-rendering device tests, verified regional downloads/manifests, a regional live-map integration path and safe-generation/fallback logic. The regional-map option is documented in code as **off by default**; the Settings area-download entry is shown only when regional mapping has been published.
- The latest Android commit on the merged PR is `Settings: Map for no signal - download my area (shown only when regional maps are published)`. A previous commit added offline label assets and a Map data & credits screen; another updated lane lookup handling for roundabouts and opposite carriageways. These are code-commit facts; nationwide on-road performance has not been independently established by this snapshot.

## 4. Greater Manchester routing acceptance: updated evidence

The earlier test failures (one apparent `no_left_turn` violation at George Street, plus three `only_u_turn` engine limitations) have been investigated in later commits. The next exact-source Greater Manchester turn-restriction acceptance run **passed**:

https://github.com/phuk-prog/drivemate-data/actions/runs/38063598159

Exact tested data commit: `7d3d1f8af750012952b9a3f008e78596fa62c37e`.

| Acceptance outcome | Count |
|---|---:|
| Total source restriction relations | 2,602 |
| Passed probe groups | 1,849 |
| Confirmed failed probes | **0** |
| Engine-unsupported restrictions | **0** |
| Route decoding mismatch | **1** |
| Inconclusive | 143 |
| Skipped | 609 |
| Known failed/unsupported blocker count in report | **0** |

Implementation and evidence described in `docs/validation/restriction-acceptance.md`:
- `scripts/restriction_rewrite.py` rewrites eligible OSM `only_u_turn` restrictions into equivalent engine-supported turn prohibitions on a **copy used to build routing graphs**, not the base OSM or rendered map; it can split ambiguous through-ways with safeguards. The acceptance run records **three rewritten** only-U-turn restrictions.
- The George Street relation `r14551046` was traced to a route-decoder mismatch in a very small street triangle, rather than a confirmed illegal manoeuvre by Valhalla. The latest report records it as **`decode_mismatch`**, not PASS or a confirmed violation. The project document describes a restricted-vs-unrestricted control that retained genuine detected failures.
- **Scope limit:** The passing workflow is an automated test of selected source restrictions using the Greater Manchester extract and routing engine. It does **not** establish that every real road sign, manoeuvre, address or junction across Manchester is correct. Skipped, inconclusive and mismatch cases remain visible for further coverage/review. The separate Valhalla-versus-OSRM cross-check workflow run `38063598125` was **cancelled**, not passed.

## 5. Map generation, publication and current running job

- The map-data source/regression workflow for the **current data development HEAD** `6000b6b5` **passed**: https://github.com/phuk-prog/drivemate-data/actions/runs/38066933528 .
- A **new manual full map-data build** on that same development commit was **in progress when checked**: https://github.com/phuk-prog/drivemate-data/actions/runs/38066967349 . Event `workflow_dispatch`, started 2026-10-10 16:16:08 UTC. Its `build` job was processing mapping data. **The final result, whether it publishes or completes all components, was not known at the snapshot.**
- A **separate earlier** map-data prerelease with tag `map-data-20261010-r38062037458-a1` was published at 2026-10-10 15:57:35 UTC. The release contains a `drivemate.pmtiles` asset of **1,639,454,841 bytes** and supporting data/licence/notice assets. This proves that this versioned GitHub prerelease exists; it does not prove that the live Android app has activated it or that the latest ongoing build has finished.
- The map-data repo commit `720b9c99129ef91173608a27d024daa767c0776a` records an **owner-approved regional publication/code change** and OSM house-number input. Workflow regional staging uses `PUBLISH_REGIONAL_MAPS`, with a default of `true` unless its repository variable overrides this to `false`. **This is distinct from the separate regional-batch queue.** The existence of a release, the publisher gate and whether a specific regional release is currently downloadable must be verified individually; none can be inferred from the other.
- Existing engineering evidence records a successful local split of a UK source archive into **207 packages (one base + 206 detailed regions)** with all 957,592 addressed source tiles accounted for exactly once. This is recorded local verification of the exporter, **not** 206 completed regional batch-ledger entries and not national real-world road validation.

## 6. Controlled regional expansion queue

Read these files on the current map-data development branch:
- `docs/regional-batch-controller.md`
- `docs/regional-batch-request.json`
- `docs/regional-batch-ledger.json`
- `scripts/region_batch_queue.py`
- `.github/workflows/regional-batch.yml`

At the snapshot:
- `docs/regional-batch-request.json`: `"enabled": false`, `"sequence": 0`.
- Ledger source identity: `8ec2a5cd5e4373a5d75243c1aa46ccb40adb3a8dd9b821f06a3b2c765f9cf069`.
- Ledger records **one completed pilot root**, Greater Manchester `8/126/82`, supported by https://github.com/phuk-prog/drivemate-data/actions/runs/38031100907 .
- There are **no confirmed subsequent completed root entries** in this ledger at the snapshot.
- The queue and map-data publisher are separate mechanisms. A prerelease published by another workflow does **not** automatically advance this ledger.
- The regional controller documentation describes source-scoped sequential or budgeted regional validation with persistent per-region evidence. The queue is **not running unattended as a GitHub cron on the development branch**.

## 7. Source/data-rights position in repository

`docs/source-rights-review.md` still describes source-rights review as **not independently verified**. It distinguishes OSM/ODbL obligations, Ordnance Survey notices, Overture/Foursquare licence and notice lineage, and imagery use. A provenance sidecar exists, but the document explicitly says provenance and fingerprints are not blanket legal clearance. The repo additionally records an owner-approved publishing change; that recorded approval and independent legal rights verification are **different facts**.

The same source review records:
- Northern Ireland OSNI gazetteer street/place integration into offline search under stated OGL attribution.
- Northern Ireland BT postcode centroid licensing concerns with LPS; permission for unrestricted offline redistribution is **not recorded as granted**. NI postcode completeness is therefore **not established**.

## 8. Scheduled controller and multi-AI coordination

- The ChatGPT automation **DriveMate UK Expansion** exists, is **enabled**, and is configured daily at about 08:00 Europe/London. When inspected, its `last_run_time` was **null**; there is no evidence here that it has completed a scheduled invocation. It is not the same thing as a GitHub scheduled workflow.
- Work from other AIs is visible through the GitHub commit history; the currently observed source heads already include such changes. The last live data-source CI and an ongoing build must not be confused with the preceding ChatGPT session's older commits or test failures.
- This document is a **snapshot only**. The exact GitHub branch heads, workflow conclusions, published release manifests and regional queue files remain authoritative for later changes. Its purpose is cross-referencing the same facts across AIs; it does not assert extra user permissions or impose a new development workflow.

## 9. Work currently open, with evidence boundaries

1. **Map-data full build underway:** run `38066967349`; no final conclusion at snapshot. Publication and completeness must be determined from its eventual run and release metadata.
2. **Map-data PR #3 not merged:** development SHA `6000b6b5`, main SHA `0dfd3354`; these are not the same branch state.
3. **Restricted-turn test coverage incomplete:** one known decoding mismatch, 143 inconclusive groups and 609 skipped relations in latest Manchester acceptance. The accepted subset has zero confirmed failing probes/unsupported cases.
4. **Separate routing cross-check cancelled:** run `38063598125` does not count as passed.
5. **Regional batch expansion remains disabled:** no blanket claim that 206 roots were processed by the ledger is supported.
6. **Data-rights status is not equivalent to a successful publisher job:** existing source review describes independent clearance and specified NI postcode permissions as unresolved.
7. **Full real-world, nationwide Android navigation acceptance has not been demonstrated by the evidence inspected.** The Android main build and device/robot verification passed for their defined scope; the presence of an APK workflow artifact is not a public release.

## 10. Direct evidence links

- Android repository and merged PR: https://github.com/phuk-prog/DriveMate ; https://github.com/phuk-prog/DriveMate/pull/3
- Android main CI and APK artifact: https://github.com/phuk-prog/DriveMate/actions/runs/38063012417
- Map-data repository and open development PR: https://github.com/phuk-prog/drivemate-data ; https://github.com/phuk-prog/drivemate-data/pull/3
- Current map-data source CI: https://github.com/phuk-prog/drivemate-data/actions/runs/38066933528
- Running full map-data workflow: https://github.com/phuk-prog/drivemate-data/actions/runs/38066967349
- Passing Manchester turn-restriction check: https://github.com/phuk-prog/drivemate-data/actions/runs/38063598159
- Cancelled Valhalla/OSRM cross-check: https://github.com/phuk-prog/drivemate-data/actions/runs/38063598125
- Versioned map-data prerelease: https://github.com/phuk-prog/drivemate-data/releases/tag/map-data-20261010-r38062037458-a1
- Original Manchester regional packaging proof: https://github.com/phuk-prog/drivemate-data/actions/runs/38031100907

**End of factual snapshot. No unstated assumptions about completed stages, release permission, licensing, route accuracy or ongoing workflow outcomes are made.**