# Turn-restriction routing acceptance (Greater Manchester)

Script: `scripts/restriction_acceptance.py`. Tests: `tests/test_restriction_acceptance.py`
(fake router, so no network or pyvalhalla needed). Workflow: `.github/workflows/manchester-acceptance.yml`.

## What it checks

The project rule is that we never invent legal turns, and routes must obey legal turn
restrictions. `restriction_audit.py` looks for malformed restriction relations in OSM. This
check goes further: it asks the routing engine the app ships (Valhalla 3.6.3, `auto` costing)
to drive through each restricted junction, and checks what the route actually does.

1. The workflow downloads the Geofabrik Greater Manchester extract and records its SHA-256.
   It builds a Valhalla graph using the same config and build commands as the `routing`
   job in `map-data.yml`, including the tar made by `valhalla_build_extract`.
2. It selects simple restrictions: `type=restriction`, with
   `restriction=no_left_turn|no_right_turn|no_straight_on|no_u_turn|only_*`, and exactly one
   `from` way, one `via` node and one `to` way. `restriction_audit.evaluate_relation` must not
   flag the relation (its one-way flags are re-derived as described below). Everything else
   is skipped and counted by reason: way-via, conditional or timed (`*:conditional`,
   `day_on`/`hour_on`…), vehicle-specific (`restriction:hgv`…), `except` covering motorcar,
   `no_entry`/`no_exit`, malformed (`needs_review:<flag>`), a from way that cannot be driven
   towards the via node (explicit or implied one-way: roundabout, motorway), a two-way from
   way that passes through the via node (approach direction ambiguous), and stretches
   shorter than 4 m.
3. For each selected restriction it builds probe routes. Each probe starts up to 40 m back
   along the `from` way, heading towards the via node, and ends up to 40 m along an exit way,
   heading away. Probe points carry a heading and `node_snap_tolerance: 0`. Without that,
   Valhalla snaps a point within 5 m of a node onto the node, so the route could start *at*
   the via node, where no restriction can apply. That gave a false FAIL during development.
   The route is plain `/route`. Its own shape is then decoded to OSM way IDs with
   `trace_attributes` (`edge_walk`, falling back to `map_snap`; each probe records which
   decoder was used).
   * `no_*`: one probe per drivable direction of the `to` way. **FAIL** if the route goes
     from way → via node → to way directly. For `no_u_turn` on a single way, a FAIL also
     needs the heading to reverse at the node. A detour around the block passes.
   * `only_*`: one probe to the `to` way, plus one probe to every other drivable exit at the
     via node, including a U-turn back onto the from way. **FAIL** if any route continues
     from the from way through the via node and leaves on a way other than the `to` way.
4. Statuses: `pass`, `fail`, `no_route` (the router found no path; recorded, never a pass) and
   `inconclusive`. A probe is inconclusive when the route did not start on the from way, did
   not end on the target way, ran against the probe direction, or could not be decoded. An
   inconclusive probe is never a pass. A relation fails if any of its probes fails. It passes
   if no probe fails and at least one probe passes.
5. The output JSON holds counts by status and skip reason, plus every failure with the
   relation, from, via and to IDs and openstreetmap.org links for human review. The exit code
   is non-zero if anything fails, and the job fails with it. Nothing is changed in OSM or in
   our data.

## What it does not prove

* **That OSM is right.** The relation is taken as given. A missing, wrong or outdated
  restriction in OSM gives a "pass" for a turn that is illegal on the street. Only ground
  truth (signs, surveys, authority data) can settle that.
* **Signage, lane-level rules, timed or conditional restrictions, and vehicle-specific
  restrictions.** These are skipped, not tested. Way-via restrictions are skipped too
  (they could be added later with a via-way chain probe).
* **Every route.** A pass covers the probed approach and exits only. Valhalla does not do
  U-turns at through junctions anyway, so `no_u_turn` passes are weak evidence (see the
  control run below).
* **The UK graph itself.** The graph is built from the county extract with the UK build
  commands. A county extract does not contain the complete UK admin boundary, so
  `valhalla_build_admins` cannot set country rules such as driving side. That changes turn
  costs, not restriction handling, but this is not byte-for-byte the published UK graph.
  Junctions near the extract edge can also lose their detours (`no_route`).

## Local evidence (2026-10-10)

Geofabrik could not be reached from the development machine. The proxy reported
`download.geofabrik.de` connections reset, as in earlier attempts, and Overpass was also
unreachable. The real Greater Manchester run is therefore the workflow. As a stand-in, central
Manchester (bbox −2.32,53.45 to −2.17,53.53, the same box as the map-data "Examine sampled
turn restrictions" step) was fetched from the OSM API in 39 tiles. The tiles were merged with
pyosmium (PBF SHA-256 `bddd2922…c868`) and built with the routing job's commands using
pyvalhalla 3.6.3.

| | Real data | Control (all restriction relations removed before building) |
|---|---:|---:|
| restriction relations | 757 | 757 (same OSM input to the checker) |
| tested | 548 | 548 |
| pass | 505 | 131 |
| **fail** | **1** | **390** |
| no_route | 0 | 0 |
| inconclusive | 42 | 27 |
| skipped | 209 (83 way-via, 69 needs review, 21 to-way one-way conflict, 12 from-way one-way, 12/7 too short, 4 conditional, 1 motorcar exception) | same |

The control shows the checker catches an engine that ignores restrictions: 390 failures.
In the control, 89 of the 100 tested `no_u_turn` relations still pass, which is why those passes
are weak evidence.

The one failure on real data is
[r13613008](https://www.openstreetmap.org/relation/13613008): `only_u_turn` on Talbot Road
(w1300451153, via n24999300). The route continues onto w112641647 instead. The Valhalla
3.6.3 tile builder knows only `only_left_turn`, `only_right_turn` and `only_straight_on`
(checked by searching the `valhalla_build_tiles` binary for its restriction strings). It
ignores `only_u_turn`, so every `only_u_turn` relation will fail this check. This is a real
gap between OSM and the engine, to be reviewed by a human. It is not a data repair.

## Known engine limitation: `only_u_turn` (status `engine_unsupported`)

Valhalla 3.6.3's tile builder does not recognise `only_u_turn`, so those
relations are not enforced and routes may ignore them. They are a real
navigation risk. The check reports them under a separate status,
`engine_unsupported`, with full relation links in the JSON and the job summary.
They now **also fail the acceptance gate**: allowing a green job while known
unsupported restrictions remain would be unsafe. New violations still appear
separately in the failing-relation list, so an existing blocker does not mask
their details.
Fixing this needs either a Valhalla release that supports `only_u_turn` or an
app-side guard; both are outstanding.

## First full Greater Manchester run — 10 October 2026

[Run 38044594966](https://github.com/phuk-prog/drivemate-data/actions/runs/38044594966)
used the Geofabrik Greater Manchester extract (retrieved 10:21 UTC) and Valhalla 3.6.3.

| Result | Relations |
|---|---:|
| Restriction relations found | 2,602 |
| Tested | 1,993 |
| Pass | 1,870 |
| Fail | **1** |
| Engine unsupported (`only_u_turn`) | 3 (r13442755, r13613008, r14121155) |
| Inconclusive | 119 |
| Skipped (mostly way-via: 316) | 609 |

**The one failure:** [r14551046](https://www.openstreetmap.org/relation/14551046),
`no_left_turn` from George Street (w210634704, one-way unclassified) via
n10003180652 into w1092418640, a two-node one-way `service=driveway`. The probe
ends on the driveway itself. The likely cause (not yet proven) is that Valhalla
does not enforce a restriction when the route's destination lies on the
restricted `to` edge. Practical impact: only when navigating to that exact
private driveway. It needs a human decision: either confirm on the ground or
in street photos and accept it, or add an app-side guard. Nothing was changed.

## Safety gate: known engine defects never counted as resolved

The machine-readable report includes known_routing_safety_blockers, the sum of confirmed failed probes and unsupported engine restriction types. The `accepted` field now requires **both** counts to be zero. It is not a production release certificate: skipped, no-route and inconclusive restrictions still need separate evidence. The r14551046 prohibited left turn was treated as a confirmed failing case at the time. A later investigation (see "r14551046 is a checker decoding error" below) showed the route was legal and the checker misread it; it was not whitelisted.

## Paired terminal-edge investigation (2026-10-10)

The Greater Manchester acceptance job repeatedly found OSM relation r14551046
(`no_left_turn`) ignored on the final destination edge of a two-node service
driveway. This remains an actual routed violation against the input relation;
the suggested terminal-edge cause is still a hypothesis, not a proven explanation.

For any node-via `no_*` restriction whose target is a two-node
`highway=service` / `service=driveway`, the checker now uses both the original
80%-of-leg destination and a second 35%-of-leg destination. Reports retain the
position and result for each probe. A failure at either destination continues
to make the entire acceptance job fail, even if the other is inconclusive or
has no route. The new synthetic regression tests this rule. This investigation
does not alter the OSM input, Valhalla graph, routing decisions or public map.

Review the next full Greater Manchester workflow result and test whether
near/far behaviour differs. Follow with a properly supported engine fix or
fail-closed route protection, validated against the same OSM relation and
related regression routes. The three `only_u_turn` engine limitations are
separate unresolved release-safety blockers.

## Conservative multi-probe verdicts

Some restriction relations require multiple probes (for example one permitted
`only_*` exit and several potentially forbidden exits, or paired terminal-edge
driveway checks). It was previously possible to report a PASS when one probe
passed but another probe was inconclusive or had no route. The verdict order is
now **fail → inconclusive → no_route → pass**. PASS requires that every probe
was successfully assessed and none broke the restriction. A terminal-edge
violation still fails even if the near-end probe is inconclusive.

Confirmed engine-unsupported `only_u_turn` restrictions now keep the
acceptance workflow red even if no supported probe fails. This is a
conservative automated test gate, not a modification of which roads are
permitted in the installed Android app. All safety issues remain outstanding
until engine support or source-backed runtime protection is implemented and
proven in replay tests.

## Stricter verdict — first Manchester comparison

A full-area run of the conservative all-probes verdict at [run 38056304326](https://github.com/phuk-prog/drivemate-data/actions/runs/38056304326) found 1,849 PASS, 140 inconclusive, 1 violation and 3 engine-unsupported restrictions out of 2,602 total relations, with 609 skipped. The earlier run had 1,870 PASS and 119 inconclusive. This shows that the previous "one passing probe is enough" verdict could conceal unresolved alternate exits. The forbidden driveway turn still fails at the 80% destination, with the 35% destination inconclusive. This is an accuracy improvement in reporting, not an engine repair.

The existing full-pass fake-router test was also corrected to supply test routes for **all four** exits instead of leaving two untested. Any known engine-unsupported type is now classified as such even when its probes are all unroutable or inconclusive. Neither adjustment changes routing behaviour in the Android app or clears the release gate.

## `only_u_turn` rewrite before graph building (10 October 2026)

Script: `scripts/restriction_rewrite.py`. Tests: `tests/test_restriction_rewrite.py`.
Valhalla 3.6.3 ignores `only_u_turn`, so before every Valhalla graph build (the
`routing` job in `map-data.yml`, this acceptance workflow and the route cross-check)
the extract is rewritten. Each simple node-via `only_u_turn` (one from way, one via
node, one to way that is the from way or a separately tagged opposite carriageway) is
replaced by the logically equivalent prohibitions Valhalla does enforce: for every
other exit that can be driven away from the via node, one `no_straight_on`,
`no_left_turn` or `no_right_turn` (bearing change under 45° is straight on), plus
`no_u_turn` back onto the from way when the U-turn goes to the opposite carriageway.
`no_entry` is not used. Every other tag (`except`, `day_on`/`hour_on`,
`restriction:conditional`, `restriction:<vehicle>`) is copied with only the type
substituted. New relations use IDs from 9,000,000,000,000 upwards, carry
`drivemate:rewritten_from`, and the original is removed. Exits on footways and
similar are not banned; an exit with unknown one-way state is banned.

Left unchanged and reported (still `engine_unsupported`, still blocking): way-via or
several from/to members, mixed restriction values, missing geometry, and a from or to
way passing through the via node. **An exit way that passes through the via node** was
also skipped at first; it is now split (see the next section). The reason is a measured engine limit: on a synthetic T-junction where the main
road is one way through the via node, Valhalla applied a simple restriction to only
one of its two edges, whatever the turn type, so the other turn stayed open.

The acceptance check is still run against the *original* extract, with
`--rewrite-report`. A rewritten relation (report SHA-256 must match the extract) is
then probed like any `only_*` relation instead of being classed engine-unsupported,
so a rewrite that did not work shows up as a failure. Anything not rewritten keeps
the old fail-closed status.

Local evidence (pyvalhalla 3.6.3, synthetic extract, before/after builds):

| Junction | Before rewrite | After rewrite |
|---|---|---|
| 4-way, only_u_turn on the south arm: straight, left, right | all taken directly | all refused (legal ring-road detour) |
| T with the main road split at the via node: left, right | both taken directly | both refused |
| T with the main road one way through the via node | taken directly | not rewritten (skipped, stays engine_unsupported) |

`restriction_acceptance.py` on the same graphs: before 2 fail + 1 unsupported, after
2 pass + 1 unsupported (exit code still 1). On live OSM data (API, 10 October 2026)
r13442755 and r13613008 would be rewritten (2 and 1 prohibitions). r14121155 (Gradient
Close) was skipped because its exit way passes through the via node; it is now handled
by splitting (next section). `route_crosscheck.py` now also reads the rewrite report.

## Splitting an exit road at the via node (r14121155, Gradient Close)

At Gradient Close the exit road (w1058575301) is one OSM way running straight through the
junction node, so it leaves the node in two directions. Valhalla 3.6.3 can ban a turn onto
only one of those two directions, so the old rewrite skipped it and the U-turn-only rule
stayed unenforced.

`restriction_rewrite.py` now splits such a way at the junction node, **in the copy used to
build the routing graph only** (the published map and the OSM data are not touched):

* The first part keeps the OSM way ID; the second part gets a new ID from
  9,000,000,000,000 upwards (the run fails if any input way already has an ID that high).
  Both parts have exactly the original tags and nodes, and share the junction node, so the
  road geometry, its rules and its connections are unchanged.
* Every relation naming the way is updated. Turn restrictions get the one part that
  touches their junction. Route and other relations list both parts in order. If any
  relation would become ambiguous (for example a different restriction that uses this same
  junction, or uses the way as a `via` way), nothing is split and the relation stays
  skipped and blocking (`split_conflicts_with_relation`). Closed (ring) ways and ways
  already split are not split (`exit_way_not_splittable`, `exit_way_already_split`).
* The `no_*` bans are then generated against the correct part (left and right turn for
  a T-junction).
* The rewrite report (schema 2) lists `split_ways` as {new way ID: original OSM way ID}
  and a `splits` record per way. `restriction_acceptance.py` and `route_crosscheck.py`
  check the report matches the extract (SHA-256), reject mappings outside the reserved range,
  and translate the new IDs back to the OSM way before judging any route. Without that
  step a forbidden turn onto the new part would look like "a different road" and could go
  unnoticed (a unit test proves this).

Evidence, pyvalhalla 3.6.3, 10 October 2026:

| Check | Result |
|---|---|
| Synthetic 4×4 grid, a T like Gradient Close, plus another restriction and a route relation on the through road | Before: both forbidden turns taken directly (148/149 m). After: both refused, legal 596/597 m detours. The other restriction (re-pointed to the new part) still enforced. |
| Same grid, split only (no new bans) vs original | 506 of 506 routes identical (length, time and shape) |
| Same grid, after vs original | 17 routes changed; every one of them used the now-banned turn before |
| Acceptance on the grid | Before: 1 engine_unsupported (all 3 probes break the rule). After: 2 pass, 0 blockers |
| Real OSM around Gradient Close (OSM API extract) | Before: r14121155 engine_unsupported, all 3 probes turn onto w1058575301. After: rewritten, 0 blockers; every probe now does the U-turn at the junction. Two exit probes are `inconclusive` (their destination snapped to a neighbouring road), so this is not counted as a pass. |

The full Greater Manchester workflow still has to confirm this on the Geofabrik extract.

## r14551046 is a checker decoding error, not an engine limitation

The Greater Manchester run reported one failure: r14551046, `no_left_turn` from George
Street (w210634704) at n10003180652 into a 7 m one-way driveway (w1092418640). The working
idea was that Valhalla ignores a ban when the route's destination is on the banned road.

**Minimal synthetic reproduction: not confirmed.** A one-way main road with a one-way
driveway ban, driveway 100 m and 7 m long, with and without a legal second way into the
junction, destination on the driveway at 80 % and 35 % and beyond it. With the ban,
Valhalla never took the forbidden turn: it used the legal detour, or answered "no route"
when there was none. Without the ban it turned directly every time. So Valhalla 3.6.3
does enforce the ban when the destination is on the banned road, and no
`destination_on_restricted_edge` status was added.

**Real cause, found on a real OSM extract around George Street.** The checker reproduced
the failure locally. But the route Valhalla returned is legal: it goes on along George
Street (w1092418641) and turns into Barn Street (w26207340), passing exactly through node
790071490, which is not on the driveway. The destination snapped onto Barn Street next to
the driveway's end. With the ban the route is 49 m; with only this relation removed it is
44 m and does use the driveway. These three ways form a tiny triangle (sides 5.1, 5.8 and
6.9 m). The checker turns the route's line back into OSM roads with Valhalla's
`trace_attributes` (`edge_walk`), and in that triangle it picked the driveway.

**Fix (stricter, not looser).** For every decision the checker makes at the junction node
(a failure or a pass), the route's own line must now lie on the OSM geometry of the
decoded roads: within 1.5 m, for up to 10 m before and after the junction, and only along
the stretch the decoder gave to each road. If it does not, the probe gets a new explicit
status, `decode_mismatch`: never a pass and never a confirmed failure, listed with links
in the JSON (`decode_mismatch`) and in the job summary. Like `inconclusive`, it is not
counted in `known_routing_safety_blockers`. This follows the owner's existing rule that a
probe that cannot be decoded is inconclusive, never a pass. It is not a release blocker,
because the route was shown to be legal, but it still needs a human look.

Proof that this does not hide real failures (real George Street extract):

| Graph | Without the line check | With the line check |
|---|---|---|
| Real restrictions | 1 fail (r14551046) | 0 fail, 1 decode_mismatch (r14551046) |
| All restriction relations removed (control) | 19 fail | the same 19 fail, r14551046 among them |

So the George Street turn still fails when the engine really takes it.
`route_crosscheck.py` uses the same decoder and does not have this line check yet.

