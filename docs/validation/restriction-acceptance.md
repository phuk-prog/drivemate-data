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

The machine-readable report includes known_routing_safety_blockers, the sum of confirmed failed probes and unsupported engine restriction types. The `accepted` field now requires **both** counts to be zero. It is not a production release certificate: skipped, no-route and inconclusive restrictions still need separate evidence. The r14551046 prohibited left turn remains a confirmed failing case pending an actual supported routing fix; do not whitelist or downgrade it.

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
several from/to members, mixed restriction values, missing geometry, a from or to
way passing through the via node, and **an exit way that passes through the via
node**. The last is a measured engine limit: on a synthetic T-junction where the main
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
Close) is skipped because its exit way passes through the via node, so it remains an
open blocker. `route_crosscheck.py` does not yet read the rewrite report and still
counts every `only_u_turn` as unenforced.
