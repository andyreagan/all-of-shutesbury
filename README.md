# All of Shutesbury

Ride every road in Shutesbury, MA. Canonical road inventory + a
CityStrides-style point checker + a standalone map tool.

**Live map:** https://andyreagan.github.io/all-of-shutesbury/ (upload a GPX
to score it). Routes: [route_conservative.gpx](route_conservative.gpx),
[route_wide.gpx](route_wide.gpx).

## The model

Instead of pass/fail on road segments, the required network is sampled into
**collectible points every 25 m** (3,078 points over 46.35 mi). A point is
collected when a ride's track passes within 25 m of it (distance measured to
the track line, so sparse GPS recording doesn't cost points). A **road is done
at >= 95% of its points** (ceil'd — roads under ~500 m still need 100%, so
junction spillover can't complete a stub). Town complete = every required
road done. Misses show up as red dot clusters on the map.

Spacing note: 25 m spacing with a 25 m radius is intentional. Credit per
track-touch is set by the radius (~2R of road) regardless of spacing; spacing
sets gap detection — at 25 m any skipped stretch > ~75 m is guaranteed to
leave a red point, while coarser spacing would let real gaps slip through.

## Data sources

- **MassDOT Road Inventory** (`data/massdot_roadinv_raw.geojson`) — ArcGIS REST
  at `gis.massdot.state.ma.us`, `City=272` (Shutesbury). Authoritative; same
  lineage as "Map 3 - Surface Type" in the town's pavement study
  (`../Scenario1.pdf`, PDF page 13).
- **OpenStreetMap** — names for unnamed MassDOT segments, supplements MassDOT
  lacks (Carver Rd East, Cove Rd / Oak Knoll extensions), town boundary
  (relation 1839614), landmark locations.
- **FRCOG Map 3 PNG** — page 13 rendered at 150 dpi, georeferenced by matching
  the town-boundary pixel extremes to its lat/lon bbox (`prep_overlay.py`,
  `data/map3_calibration.json`), white made transparent for overlay use.
- **There is no newer official town map.** The Master Plan says the town has
  no official Town Map (was using a 1999 version); the "Shutesbury Town Map"
  PDF on shutesbury.org (`data/shutesbury_town_map.pdf`) is a scan packet —
  an Arrow street-atlas page plus fire-dept run maps (Lake Wyola page dated
  2013, with house numbers). Useful as a tie-breaker on whether a road
  exists, not as geometry. Freshest authority = MassDOT Road Inventory
  (last edited 2026-07-31) + OSM; the 2004 FRCOG map is the town's-eye view.

## Files

- `build_roads.py` — rebuilds `data/roads.geojson` (283 segments, ~68.6 mi),
  `data/boundary.geojson`, and `data/points.json` (the 25 m collectible points
  on required roads).
- `check_route.py` — CLI scorer:
  `uv run check_route.py RIDE.gpx [more.gpx ...] [--radius 25]`
  Prints points collected, verdict, and per-road missed counts.
- `make_map.py` — builds **`map.html`**, the self-contained canonical map
  (~1.3 MB, data + Map 3 overlay inlined; internet needed only for basemap
  tiles): FRCOG Map 3 overlay with opacity slider, road inventory (required
  solid, optional dashed), all points. **Upload GPX file(s) in the browser**
  to color points green/red and get per-road stats. Verified to produce
  identical results to `check_route.py`.
- `prep_overlay.py` — regenerates the georeferenced overlay PNG from
  `data/map3_page-13.png` (render with
  `pdftoppm -f 13 -l 13 -r 150 -png ../Scenario1.pdf data/map3_page`).

## Hand edits

`edits.json` (next to the scripts) survives rebuilds:

```json
{"require_segments": [], "exclude_segments": [], "exclude_points": []}
```

- **Bad point** (e.g. sits on a house): tick "Edit mode" in `map.html`, click
  the point (turns dark, tooltip shows its id like `S123-4`), click "Download
  edits.json", replace the file, rerun `build_roads.py` + `make_map.py`.
  Or just add the id by hand.
- **Segment shouldn't count / should count**: put its seg_id in
  `exclude_segments` / `require_segments`.
- **Segment line doesn't follow the real road**: draw the corrected line at
  geojson.io, save as a feature with `"properties": {"seg_id": "S123"}` in
  `data/custom_geometry.geojson`; the build swaps in your geometry (its
  points are resampled, so old point ids for that segment change).

## What counts (46.35 mi required → 3,078 points)

General rule: every town/MassDOT road, DCR west of 202, and every *named*
unaccepted/private road counts. Trails, tracks, and unnamed driveways don't.

## Special decisions

These are what make the dataset. Mechanics live in `build_roads.py`
(`SUPPLEMENTS` / `RENAMES` / `QUABBIN_EXCLUDE`), `edits.json`, and
`data/custom_geometry.geojson` — update this list when a ruling changes.

- Everything east of 202 is well into DCR (Quabbin), so we probably can't
  ride Prescott on the east, and Enfield doesn't count — MassDOT not having
  it makes sense. West-of-202 DCR does count: New Boston, Cornwell.
- The last ~450 ft of 202/Cooleyville out to the New Salem line count
  (S257, S282, S283).
- Weatherwood + High Point to boundary — the overlook is past the town line,
  so the in-town stub (S083) is all there is.
- SES driveway (S036): bit of a nit-pick, but it's on the map.
- Cemetery driveway: was in as a nitpick, but the town map stub there is
  actually Wilson Rd (S154) — whole cemetery network optional (S178 is the
  real access off Leverett if we ever want it back).
- Town Farm Rd: map has this almost to 202 — you'd have to pass the gate and
  ride the trail. All of it counts.
- Is Briggs Rd a driveway? Doesn't appear so. Counts.
- NET Trail: hiking trail, not a road. Optional.
- Macedonia Rd: town map doesn't show the north section, and MassDOT's line
  doesn't line up with OSM near the bottom — the whole corridor is MassDOT's
  "NET TRAIL". Optional; the south residential stub off Cooleyville is in as
  X283 if we change our minds.
- Gass Lite Lane (S141): the road living up to its name — gaslighting
  MassDOT. Their line cut across lot 145; replaced with OSM geometry.
- Community Center Dr (S176): not on the town map, but it connects easily to
  Farmhouse Dr (S155), so keep it — do both in one pass when routing.
- S035 (Leverett Rd fragment near the SW town line): not on the town map,
  but keep it and try it.
- Carver Rd East, Cove Rd + Oak Knoll extensions (X279–X281): real roads
  MassDOT truncates or lacks, added from OSM.
- Hand-excluded points (`edits.json`): S171-0, S172-0, S173-1, S271-1 —
  MassDOT lines overshooting into houses.
- S001: 0.9 mi unnamed paper road north of town center, no OSM counterpart,
  no visible road. Optional.
- Ames Haven Rd (S170): we have it and the town map doesn't. Keep.
- Ames Pond driveway (X284): the town map has the driveway for the house at
  Ames Pond but MassDOT doesn't — probably a town road. Added from OSM
  (way 895253236), required. OSM only maps the east half — first pass left a
  big gap to Wendell Rd, so the build prepends the missing western stretch
  (`prepend_from` in `SUPPLEMENTS`) to join it back to Wendell.
- Ladyslipper: we have quite a bit more than the town map shows. OSM agrees
  with MassDOT, keep ours.
- Mt Mineral: all of it excluded, pending ground truth. The south side
  (S023) is what OSM actually calls Mt. Mineral Rd — town doesn't have it,
  and it's really not a road (a track; New Boston is hardly a road either,
  but I want it). The north chain (S021/S162/S163, east of Lake Wyola) isn't
  on the town map either, and MassDOT's "Mount Mineral" name there looks
  misapplied — it sits exactly on an *unnamed* OSM residential lane +
  service track. Unnamed lane = doesn't count, until someone rides it and
  says otherwise.

## Routing notes

Local knowledge for the route planner:

- A lot of the stuff around New Boston are historical real roads, Town Farm
  included — gated/rough but passable.
- Carver Rd / Carver Rd West / Carver Rd East can be connected on the ground —
  prefer connecting them (I'd actually like to, if it makes sense).
- Jennison can be ridden through from the north side via New Boston Rd
  (Wendell side) — no need for an out-and-back from Locks Pond.
- Sirius Community Center Dr connects to Farmhouse Dr — do both in one pass.
- A little doubling of points along Gass Lite Ln — perhaps that's okay.
- Town Farm Rd: pass the gate, ride the trail to near 202.

## Town map errata

Where Map 3 is just wrong — trust MassDOT/OSM, don't chase the overlay:

- Town Farm Rd: the map's drawing is way off.
- Middle of Baker Rd drawn as paved — that's never been the case. A mistake.

## Baseline: friend's attempt (`friend_ride.gpx`)

2601/3078 points (84.5%); 29/73 roads done, 44 to go. Biggest gaps:
Town Farm Rd (2.4 km), Cornwell Rd (0.8 km), Weatherwood (0.6 km),
plus ~40 smaller roads/stubs.

## Routes (`route_wide.gpx`, `route_conservative.gpx`)

`uv run plan_route.py --policy wide [--conservative]` — Rural Postman from
Town Hall: connect required components via cheapest connector paths, even
out odd-degree nodes via min-weight matching, Euler circuit. Both variants
validated **TOWN COMPLETE** (3078/3078 points, 73/73 roads) by
`check_route.py`; drop a GPX into `map.html` to see it.

| feature | trusting | conservative | friend's 85% ride |
|---|---|---|---|
| distance | 76.0 mi | 76.8 mi | 60.7 mi |
| unique required | 46.1 mi | 46.1 mi | 39.1 mi |
| repeats/connectors | 29.9 mi (39%) | 30.7 mi (40%) | — |
| U-turns (dead-end turnarounds) | 66 | 70 | — |
| unverified links used | 6 | 0 | — |
| elevation gain (est) | ~5,000–5,500 ft | same | 4,379 ft |

Both use the confirmed links: Carver straight shot (1.16 km),
Sirius<->Farmhouse (54 m), New Boston north end -> Jennison (321 m).
The trusting one additionally assumes these are passable — verify before
riding it: Kettle Hill (119 m), South Laurel (180 m), Cooleyville east
stub (265 m), Leverett (53 m), Wyola (24 m). The conservative one
out-and-backs those spurs instead, for only +0.8 mi — probably the one
to ride.

Other planner findings:
- In-town-only routing is **infeasible** — the required network needs
  out-of-town pavement (Wendell, New Salem) just to connect.
- Elevation estimated from the friend's GPX used as a DEM (81% coverage,
  same smoothing both sides); Open-Meteo was rate-limited.
- Route total is essentially fixed by the required set; the only real
  variation axis is trust in unverified connections.
