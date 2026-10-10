# Route cross-check: Valhalla vs OSRM (Greater Manchester)

Script: `scripts/route_crosscheck.py`. Tests: `tests/test_route_crosscheck.py` (fake routers, no
network, no pyvalhalla or OSRM needed). Workflow: `.github/workflows/route-crosscheck.yml`.

## What it does

DriveMate routes offline with Valhalla 3.6.3 on OpenStreetMap. This check drives the same
journeys through a second, independent open-source engine, OSRM (car profile), built from the
**same** Geofabrik Greater Manchester extract (one download, SHA-256 recorded and re-checked
before the OSRM build). Where the two disagree, a person takes a look.

1. **Journeys.** 300 seeded random journeys by default (the seed is fixed, so every run asks the
   same questions of a given extract), split evenly into short (0.5–3 km), medium (3–15 km) and
   long (15–40 km) straight-line bands, plus four fixed journeys: Stockport town centre → SK8 2EZ
   (Menai Grove, 53.395466, -2.194193), Manchester Piccadilly → Manchester Airport, a journey
   through the Pyramid roundabout (M60 J1) and one through M60 J4 (the M56 split). Endpoints are
   snapped to the nearest road with OSRM `/nearest`, and both engines get the same snapped point.
   For the two junction journeys the report records whether each route passed within 400 m of
   the junction (information only; the junction points are approximate).
2. **Routing.** Valhalla through pyvalhalla (`auto` costing; the route shape is decoded to OSM
   way IDs with `trace_attributes`, `edge_walk` then `map_snap`). OSRM through a local
   `osrm-routed` (`ghcr.io/project-osrm/osrm-backend:v6.0.0`, pinned by digest, MLD) with
   `annotations=nodes`; consecutive OSM node pairs are mapped back to ways from the extract.
3. **Flags** (per journey, per engine where it applies):
   * `no_route_one_engine`: one engine found a route, the other did not.
   * `distance_ratio`: the longer route is more than 1.25× the shorter (`--ratio`).
   * `restriction_violation`: a turn that breaks a simple node-via `no_*`/`only_*` restriction.
     Relations are selected with `restriction_acceptance.classify`, so the same conditional,
     timed, vehicle-specific, way-via and malformed relations are skipped (counted by reason).
     A turn only counts when the route arrives along the relation's `from` way, from a
     direction a car may legally drive towards the via node.
   * `oneway_violation`: a stretch driven against an explicit or implied one-way (roundabouts,
     motorways), using the same one-way rules as the restriction check. Reversible or unknown
     values are never assumed either way.
   * `u_turn`: the heading reverses (150° or more) between two consecutive stretches.
4. **Output.** `route-crosscheck.json` (every journey: both engines' distance, duration, way
   sequence and flags) and `route-crosscheck.md` (counts and the top 25 flagged journeys, each
   with an openstreetmap.org directions link and way/relation links). Both are uploaded as an
   artifact and the Markdown goes to the job summary.

### When the job fails

Only for **Valhalla** restriction or one-way violations, because that is the engine the app
ships. OSRM violations, U-turns, ratio and no-route flags are leads and never fail the job.
As in `restriction_acceptance.py`, restriction types Valhalla 3.6.3 does not build into its
graph (`only_u_turn`) are listed as blockers whenever the extract contains a testable one, even
if no journey happened to cross it. The JSON field `known_routing_safety_blockers` counts both.

## What it proves, and what it doesn't

* It finds places where two independent engines read the same map differently, or where
  Valhalla's route breaks a rule written in that map. That is a cheap way to find suspicious
  junctions across a whole county.
* It does **not** prove OSM is right. Both engines read the same data, so a missing or wrong
  restriction or one-way in OSM is invisible when both obey it.
* Agreement is not proof that a route is legal or sensible. Disagreement is not proof that
  either engine is wrong: two legal routes can differ by more than 25% when the costs differ
  (OSRM and Valhalla weigh road types and turns differently).
* No live traffic, signage, lane or time-of-day checks; way-via and conditional restrictions are
  not checked.

## How to triage a flag

1. Open the openstreetmap.org link and look at the junction, ways and relation named in the flag.
2. Check the real world: street-level photos (Mapillary, or other imagery whose terms allow
   viewing for this purpose), signs and road markings, or a local survey. Never copy data from
   Google, TomTom, Waze or Apple into OSM or our database.
3. If OSM is wrong, fix it **by hand** in OpenStreetMap with a clear changeset comment. The fix
   flows back to DriveMate through the weekly map build. This tool never edits map data.
4. If OSM is right and Valhalla broke the rule, record it as a routing-safety blocker (as with
   restriction acceptance) until the engine or a verified route guard handles it.
5. If both are legal, no action is needed.

## Legal boundary

Only open-source engines (Valhalla, OSRM) run on our own copy of OpenStreetMap data (ODbL). No
commercial routing service, map tile or traffic feed is queried, stored or compared, and nothing
is uploaded except the report artifact.

## Running locally

```
docker run --rm -v "$PWD/work/osrm:/data" ghcr.io/project-osrm/osrm-backend:v6.0.0 osrm-extract -p /opt/car.lua /data/gm.osm.pbf
docker run --rm -v "$PWD/work/osrm:/data" ghcr.io/project-osrm/osrm-backend:v6.0.0 osrm-partition /data/gm.osrm
docker run --rm -v "$PWD/work/osrm:/data" ghcr.io/project-osrm/osrm-backend:v6.0.0 osrm-customize /data/gm.osrm
docker run -d -p 5000:5000 -v "$PWD/work/osrm:/data" ghcr.io/project-osrm/osrm-backend:v6.0.0 osrm-routed --algorithm mld /data/gm.osrm
python scripts/route_crosscheck.py --pbf work/gm.osm.pbf --graph work/gm.tar --journeys 50 \
  --report work/route-crosscheck.json --markdown work/route-crosscheck.md
```

The Valhalla tar is built as in `manchester-acceptance.yml`.
