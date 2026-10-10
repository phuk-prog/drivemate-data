# DriveMate national regional batch controller (unpublished)

**Decision:** finish generic app / UK map features before enabling full regional rollout. Greater Manchester is the first end-to-end acceptance region. Other z8 roots run one-by-one, nearest to Manchester first, with z9/z10 child packages staying together.

Files:
- `scripts/region_batch_queue.py` — deterministic, resumable selection and result admission
- `docs/regional-batch-ledger.json` — durable checksum-source-scoped completed-region proof
- `docs/regional-batch-request.json` — optional per-run request, initially DISABLED
- `.github/workflows/regional-batch.yml` — isolated, read-only regional audit runner

Rules:
1. A run downloads only the pinned and verified existing UK map. It neither derives extra map material from imagery nor publishes map data.
2. The nationwide base and one regional root (including all dense subdivisions) must pass PMTiles integrity checks. A root is completed only if all packages pass and evidence is preserved.
3. Exactly one region is processed per run, with the same `map-data` concurrency group as the full UK generator. No overlapping expensive builds.
4. The source archive SHA-256 is a generation identity. If it changes, the queue must be explicitly migrated/reverified, not silently combined.
5. The status ledger is updated with an immutable run URL and per-package SHA-256/byte/tile summaries. Map archives are **not** uploaded to GitHub. This performs testing, not map distribution.
6. The queue begins with the already validated Manchester root; remaining regions are prioritised outward from Greater Manchester.
7. An unchanged completed area is never processed again in the same source generation; failed regions remain eligible for repair/retry.
8. Bulk expansion is held until shared code, Manchester real Android rendering, legal source review and the full compatibility tests pass. A successful synthetic emulator case is not sufficient to release a live map.

**Scheduling limitation:** GitHub `schedule` only triggers workflows located on the default branch. This development branch prepares the executable workflow but does not create a working unattended GitHub cron on its own. A separate scheduled DriveMate controller can request a run by committing a new approved `docs/regional-batch-request.json` sequence after release gates, triggering this branch's push workflow. Do not merge the entire development branch to main simply to enable cron. If scheduled directly on GitHub, merge only the vetted scheduler to `main` after approval, with code explicitly checked out from the tested revision.

## Scheduled idempotency

Disabled requests exit without downloading maps. Every enabled request must have an increasing integer sequence, and only a fully verified successful region can advance `last_sequence` in the ledger. Replaying one run cannot mark another regional root completed. The initial Manchester-only validation remains the existing seeded entry.

## Multi-region requests and resume (added 10 October 2026)

One approved request can now authorise several regions: set
`"max_roots": N` (1–200, default 1) alongside `"enabled": true` and a new
`"sequence"`. The workflow downloads and checksum-verifies the UK source
**once**, then loops: select the nearest unverified z8 root, export it,
verify every archive, admit it to the ledger and **commit + push that
single region before starting the next**. The ledger records
`last_sequence` and `sequence_roots` (regions committed under it).

- An interrupted or timed-out run is resumed by re-running the workflow
  (manual dispatch) with the same request: committed regions are skipped and
  the remaining budget is `max_roots - sequence_roots`.
- A request whose budget is spent is refused; continuing needs a new,
  higher sequence. Ledgers written before this change are treated as having
  spent their last sequence, so they can never be replayed.
- No region starts after 270 minutes of a 300-minute job, so evidence is
  always uploaded and no region is left half-recorded.
- Map archives are deleted after each region; only manifests and
  verification reports are retained as evidence.

Each `regional-manifest.json` also lists, per detail package, the companion
`lanes`/`limits`/`roadinfo` (half-degree) and `places` (quarter-degree)
squares overlapping it, plus the nationwide files, so the phone can fetch
everything an offline region needs (`scripts/region_companions.py`). With
`--release-manifest`, squares absent from the release are dropped rather
than invented.

**Activation remains held**: `docs/regional-batch-request.json` stays
`enabled: false` until the shared-code, Manchester acceptance and
source-rights gates in `docs/map-development-master-plan.md` pass.
