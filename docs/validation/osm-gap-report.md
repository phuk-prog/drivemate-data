# OpenStreetMap gap report (Greater Manchester)

## What it is

`scripts/osm_gap_report.py` reads the Geofabrik Greater Manchester extract and lists places where OpenStreetMap
(OSM) is missing data DriveMate would use. The `manchester-gaps` workflow runs it and uploads
`osm-gaps.json` and `osm-gaps.md`; the top 30 appear in the run summary. It is informational: it never fails on
gaps, never changes data and never guesses values.

It lists:

1. Approaches to junctions on motorway, trunk, primary and secondary roads with `lanes` of 2 or more but no
   `turn:lanes` (or `turn:lanes:forward/backward`). The way containing the junction is reported, so the approach
   within about 150 m of the junction is the stretch to check.
2. Motorway, trunk, primary, secondary and tertiary ways with no `maxspeed`.
3. `motorway_link` and `trunk_link` slip roads with no `lanes`.

Items are ranked by owner-route priority, then road class, then length. Each has an openstreetmap.org link and an
iD editor link. Priority means within 300 m of the owner's routes: M60 J1-J4 (Stockport), M56 J1-J3, A34
Cheadle/Gatley, A560 Stockport-Cheadle, and SK8 2EZ (53.395466,-2.194193). The corridors are rough areas matched by
road reference, for ranking only; they can be replaced with `--corridors <file.json>`.

## How to fix an item in OSM

Only add what you have seen yourself. Survey on the ground, or use your own observations (for example, lanes you
noticed while driving, or signs you photographed yourself).

- Do not copy from Google, TomTom, Waze, Apple or Mapillary imagery or data; their terms do not allow it and OSM
  must not receive copied data.
- Open the iD link, select the way, and add `turn:lanes` (for example `left|through|through;right`), `lanes`, or
  `maxspeed` (for example `30 mph`). Split the way at the junction first if the lane layout changes part-way.
- On one-way roads use `turn:lanes`; on two-way roads use `turn:lanes:forward` and `turn:lanes:backward`.
- Add a short changeset comment such as "Surveyed lanes at <junction>", and leave the item alone if you are unsure.

Fixes reach DriveMate through the weekly map build after OSM and Geofabrik update.
