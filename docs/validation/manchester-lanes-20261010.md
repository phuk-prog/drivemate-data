# Greater Manchester lane guidance acceptance — 10 October 2026

This run checks six lane layouts that the owner recorded as verified on real roads
(app repo `CLAUDE.md`) against DriveMate's **published** lane squares. The owner's
descriptions are **reports to check**, not ground truth. OpenStreetMap may be right or
wrong at each place, and so may the reports. **Nothing was changed**: no lane file, OSM
object, release or app code was edited. Every result below is what the published data
says, matched the way the phone matches it.

## Inputs

- Pointer `map-data-uk/latest.json` (SHA-256 `2495d8b9ec5b4e52b85de95cd4454aa4d0f39d4f84231aeb2ae5424f2cef317a`)
  names `manifest_tag` **`map-data-20261008-bootstrap`** and `manifest_sha256`
  `1ce4935da3277bbf90d2cf5abd91c8d16fd3f025de1fbce84f5215cbc73c63ae`.
  The downloaded `manifest.json` hashes to that value. The manifest describes itself as
  "Existing legacy assets only".
- Lane squares, each downloaded from the tag its manifest entry names (`map-data-uk`),
  with size and SHA-256 matching the manifest:

  | Asset | Release tag | Bytes | SHA-256 |
  |---|---|---|---|
  | `lanes-106_-5.json` | `map-data-uk` | 3,337,728 | `8902562a78e922ef01fa05c09e9d092b54c6fd02830aab635f07a553610cf300` |
  | `lanes-106_-4.json` | `map-data-uk` | 972,184 | `8285bb34c01d39da9d0261dbfad5d80dc70b91b6932fe8dd8d2b8f4e045a5247` |

  All six checkpoints lie in square `106_-5`. `106_-4` was loaded as well, as the phone
  would load neighbouring squares. In total 15,194 distinct ways were indexed.
- Checkpoints: [`manchester-lanes-checkpoints.json`](manchester-lanes-checkpoints.json).
  It records how each one was located: lane-file way names and refs, Nominatim
  search/lookup/reverse, and small read-only OSM API bounding-box reads. No proprietary
  source was used.

Reproduce with:

```bash
python scripts/lane_acceptance.py --lanes lanes-106_-5.json lanes-106_-4.json \
  --checkpoints docs/validation/manchester-lanes-checkpoints.json \
  --json-out result.json --md-out result.md
```

## How matching works

`scripts/lane_acceptance.py` ports `LaneDb` from `OwnMap.kt`. Segments are filed in
0.002° cells together with their neighbouring cells. The nearest segment **under 20 m**
wins. A segment counts as forward when its bearing is **within 40°** of the heading and
as backward when it is **more than 140°** away; anything between is a crossing road and
is skipped. The lane count follows `laneCountAt`. The arrows follow `lanesAt`, read
before its manoeuvre filter. Each checkpoint also names the OSM way it lies on, and
matching any other way counts as a MISMATCH.

Verdicts:

- **MATCH**: everything that was checked agrees.
- **MISMATCH**: something present disagrees, or the phone would read a different road.
- **NO_DATA**: no way matched, or an expected item (arrows or count) is missing and
  nothing disagrees.

## Results

Summary: **2 MATCH, 2 MISMATCH, 2 NO_DATA**. The data holds **no lane arrows
(`turn:lanes`) on any of the six roads**. Only lane counts could be compared.

| # | Checkpoint (lat, lon, heading) | Verdict | Matched way | Lanes data / expected | Arrows data / expected |
|---|---|---|---|---|---|
| 1 | Brinksway lights approach, A560 eastbound (53.406701, -2.174396, 44°) | **NO_DATA** | [2246322](https://www.openstreetmap.org/way/2246322) A560 Brinksway | 2 / 2 ✔ | none / [straight \| right] |
| 2 | Pyramid Roundabout approach, M60 J1, Hollywood Way northbound (53.408165, -2.174406, 350°) | **MATCH** | [954327639](https://www.openstreetmap.org/way/954327639) A560 Hollywood Way | 4 / 4 ✔ | none / not checked |
| 3 | M60 J4 westbound before the M56 split (53.399018, -2.223984, 257°) | **MISMATCH** | [30631502](https://www.openstreetmap.org/way/30631502) M60 | 4 / 5 ✘ | none / not checked |
| 4 | M56 J2 Sharston exit slip approaching the roundabout (53.39596, -2.25555, 293°) | **NO_DATA** | none within 20 m | – / 2 | none / [right \| right] |
| 5 | M60 J2 eastbound before the A560 exit (53.400757, -2.215797, 67°) | **MATCH** | [135848914](https://www.openstreetmap.org/way/135848914) M60 | 4 / 4 ✔ | none / not checked |
| 6 | Roscoe's Roundabout exit into Carrs Road (53.39758, -2.19982, 190°) | **MISMATCH** | [953769398](https://www.openstreetmap.org/way/953769398) Roscoe's Roundabout (not Carrs Road) | 1 / 1 (by accident) | none / not checked |

A read of the OSM API on 10 October 2026 shows that every way named below currently
has the same `lanes`/`turn:lanes` tags as the published squares. The published data is
therefore not stale for these places. Whatever differs from the reports differs in OSM
itself.

## Details and links for human review

### 1 Brinksway — NO_DATA (count agrees, arrows missing)
- Our data: way 2246322 has `oneway=yes`, `lanes=2` and no `turn:lanes`. The phone would
  show no lane arrows here.
- OSM topology just after this point is a split at 53.40691,-2.17397. On the left is a
  1-lane `primary_link` ([954026108](https://www.openstreetmap.org/way/954026108)) to
  Hollywood Way northbound, towards the Pyramid Roundabout and M60 J1. Straight on is
  1-lane Brinksway ([954199038](https://www.openstreetmap.org/way/954199038)). Both have
  signals. That reads like [left | straight], not the reported [straight | right].
  Either the report refers to another arm, or OSM is wrong. Check on the ground or from
  imagery before adding `turn:lanes`.
- Ways to check: [2246322](https://www.openstreetmap.org/way/2246322),
  [1291544924](https://www.openstreetmap.org/way/1291544924).

### 2 Pyramid Roundabout approach — MATCH (count only)
- Way 954327639 has `lanes=4`. A separate 2-lane `motorway_link`
  ([1059611956](https://www.openstreetmap.org/way/1059611956)) leaves on the left
  towards the M60. "2 left lanes to the M60" cannot be checked without `turn:lanes`.

### 3 M60 J4 before the split — MISMATCH (4 vs 5)
- Way [30631502](https://www.openstreetmap.org/way/30631502) has `lanes=4` along its
  whole 527 m. Beyond the split at 53.39852,-2.22843, OSM has M56
  [4966822](https://www.openstreetmap.org/way/4966822) with `lanes=2` and M60
  [979363523](https://www.openstreetmap.org/way/979363523) with `lanes=3`.
  That makes 5 lanes after the split, which agrees with the report's "M56 takes the 2
  left of 5". OSM may be missing a lane gain just before the split, or the 5 lanes may
  only exist at the nose. Check where the fifth lane starts.

### 4 M56 J2 Sharston exit slip — NO_DATA
- The exit slip [4966832](https://www.openstreetmap.org/way/4966832) (`motorway_link`,
  destination Altrincham;Wythenshawe;Liverpool;Bolton) has **no `lanes` or `turn:lanes`
  tags**, so it is not in the lane file. The nearest lane ways are the Sharston Link
  mainline ([998796122](https://www.openstreetmap.org/way/998796122),
  [4972152](https://www.openstreetmap.org/way/4972152)), each 21.2 m away, just outside
  the 20 m limit. Nearer the start of the slip, the phone would pick up the mainline's
  2 lanes instead.
- Candidate OSM fix, if the report is confirmed: `lanes=2` and `turn:lanes=right|right`
  on the slip's final section.

### 5 M60 J2 — MATCH (count only)
- Way 135848914 has `lanes=4`. It then splits into a 2-lane exit
  ([1560300318](https://www.openstreetmap.org/way/1560300318), Cheadle A560) on the left
  and the 3-lane M60. "Left lanes exit" is not encoded as arrows.

### 6 Roscoe's Roundabout → Carrs Road — MISMATCH (wrong road)
- In OSM, Carrs Road leaves directly from the roundabout's south-east side as one-way way
  [4953964](https://www.openstreetmap.org/way/4953964). It has no lane tags, so it is not
  in the lane file. The phone falls back to circulatory way
  [953769398](https://www.openstreetmap.org/way/953769398) (`junction=circular`,
  `lanes=2`, no `oneway`). `laneCountAt` then halves it to 1. The count "agrees" only by
  accident.
- No Carrs Road connection about 130 m beyond the roundabout was found. A human should
  check where the reported separate lane is.

## Consumer behaviour seen (app code, not data; reported, not changed)

- `laneCountAt` only checks `oneway`. A `junction=roundabout` or `junction=circular` way
  without `oneway` gets half its lanes; checkpoint 6 shows this. `lanesAt` handles
  `junction=roundabout` but not `circular`.
- `nearest` ignores `oneway`. On dual carriageways closer than 20 m it can pick the
  opposite carriageway. The tool flags this as `against_oneway` and also reports a
  strict match. It did not happen at these six checkpoints.

## Limits

- Checkpoint placement is our reading of short descriptions. The uncertainty of each one
  is written in the checkpoints file, and checkpoints 1, 4 and 6 are the least certain.
- Only lane counts could be tested, because none of the six roads has arrows in OSM.
