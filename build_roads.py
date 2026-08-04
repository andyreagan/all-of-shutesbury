"""Build the canonical Shutesbury road inventory (data/roads.geojson).

Sources:
  - data/massdot_roadinv_raw.geojson  (MassDOT Road Inventory, City=272) — authoritative
  - data/osm_highways_raw.json        (OSM ways with highway=* inside town) — supplements
  - data/osm_boundary_raw.json        (OSM town boundary relation)

Output:
  data/roads.geojson    one feature per segment: seg_id, name, source,
                        jurisdiction, surface, category, length_mi, required
  data/boundary.geojson town polygon

Required tiers:
  - public roads (town / MassDOT / DCR / unknown jurisdiction): required
  - named unaccepted/private roads: required (the point is to ride everything)
  - OSM supplements listed in SUPPLEMENTS with required=True: required
  - trails, tracks, driveways, unidentified paper roads: optional

Hand edits live in edits.json (survives rebuilds; exportable from map.html):
  {"require_segments": [seg_ids], "exclude_segments": [seg_ids],
   "exclude_points": [point_ids]}
Point ids are stable: "<seg_id>-<index>" (stable while the segment's geometry
is unchanged). To fix a segment whose line doesn't follow the real road, put a
corrected LineString in data/custom_geometry.geojson with properties.seg_id
(draw it at geojson.io); it replaces that segment's geometry.
"""

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import linemerge, polygonize, transform, unary_union

DATA = Path(__file__).parent / "data"
TO_M = Transformer.from_crs(4326, 26986, always_xy=True).transform
TO_DEG = Transformer.from_crs(26986, 4326, always_xy=True).transform

JURISDICTION = {"0": "unaccepted/private", "1": "MassDOT", "2": "town", "3": "DCR", None: "unknown"}
SURFACE = {
    "0": "unimproved/other", "1": "unimproved", "2": "gravel",
    "5": "paved (bituminous)", "6": "paved (surface treated)", None: "unknown",
}
NAME_FIXES = {"MT. MINERAL ROAD": "MOUNT MINERAL ROAD"}

# OSM roads missing from (or truncated in) MassDOT. extend=True keeps only the
# part farther than 30 m from same-name MassDOT geometry.
SUPPLEMENTS = {
    "ENFIELD ROAD": {"jurisdiction": "DCR", "required": False, "extend": False},
    "CARVER ROAD EAST": {"jurisdiction": "unaccepted/private", "required": True, "extend": False},
    "HIGH POINT DRIVE": {"jurisdiction": "unaccepted/private", "required": True, "extend": True},
    "COVE ROAD": {"jurisdiction": "unaccepted/private", "required": True, "extend": True},
    "OAK KNOLL": {"jurisdiction": "unaccepted/private", "required": True, "extend": True},
    "GATE LANE": {"jurisdiction": "unaccepted/private", "required": False, "extend": True},
    # south residential stub off Cooleyville; rest of the corridor is the NET
    # trail (MassDOT "NET TRAIL", not on the town map) and stays optional
    "NORTH MACEDONIA ROAD": {"jurisdiction": "unaccepted/private", "required": False, "extend": False},
    # on the town map (gravel stub off Wendell Rd), unnamed in OSM/MassDOT.
    # OSM only maps the east half; prepend_from joins it back to Wendell Rd.
    "AMES POND DRIVEWAY": {"jurisdiction": "unknown", "required": True, "extend": False,
                           "way_ids": [895253236],
                           "prepend_from": (-72.42114, 42.49490)},
}

# Identified unnamed MassDOT segments (keyed by original massdot index, see seg_id).
RENAMES = {
    "S036": ("SES DRIVEWAY", True),
    # the map stub near here is Wilson Rd, not the cemetery; whole cemetery
    # network optional (S178 is the actual access from Leverett Rd if wanted)
    "S178": ("CEMETERY DRIVEWAY", False),
    "S179": ("CEMETERY ROAD", False),
    "S180": ("CEMETERY ROAD", False),  # interior row, disconnected from network
    "S181": ("CEMETERY ROAD", False),
    "S182": ("CEMETERY ROAD", False),
    "S183": ("CEMETERY ROAD", False),
    "S184": ("CEMETERY ROAD", False),
    "S185": ("CEMETERY ROAD", False),
    "S041": ("PRESCOTT ROAD (gate section)", False),  # Quabbin side, east of 202
}

# Quabbin watershed roads east of Route 202 (DCR land, riding not clearly
# allowed): Prescott Rd east-of-202 chain. Not required.
QUABBIN_EXCLUDE = {"S042", "S118", "S119", "S120"}


def load_osm_ways():
    d = json.load(open(DATA / "osm_highways_raw.json"))
    ways = []
    for e in d["elements"]:
        if e["type"] != "way" or "geometry" not in e:
            continue
        coords = [(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(coords) < 2:
            continue
        ways.append({"osm_id": e["id"], "tags": e.get("tags", {}),
                     "geom_m": transform(TO_M, LineString(coords))})
    return ways


def build_boundary():
    d = json.load(open(DATA / "osm_boundary_raw.json"))
    lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in d["elements"][0]["members"]
             if m["type"] == "way" and m.get("geometry")]
    poly = max(polygonize(linemerge(unary_union(lines))), key=lambda p: p.area)
    with open(DATA / "boundary.geojson", "w") as f:
        json.dump({"type": "Feature", "properties": {"name": "Shutesbury"},
                   "geometry": poly.__geo_interface__}, f)
    return poly


def osm_label(way):
    t = way["tags"]
    if t.get("name"):
        return t["name"]
    hw = t.get("highway", "?")
    return f"service/{t.get('service', 'driveway?')}" if hw == "service" else hw


def category(name, named_in_massdot, jurisdiction):
    if "TRAIL" in name.upper():
        return "trail"
    if named_in_massdot or jurisdiction != "unaccepted/private":
        return "road"
    if name.startswith("service/"):
        return "driveway"
    if name in ("track", "path") or "Loop" in name or name.startswith("Gate "):
        return "trail/track"
    return "other"


def load_edits():
    edits = {"require_segments": [], "exclude_segments": [], "exclude_points": []}
    path = Path(__file__).parent / "edits.json"
    if path.exists():
        edits.update(json.load(open(path)))
    return edits


def load_custom_geometry():
    path = DATA / "custom_geometry.geojson"
    if not path.exists():
        return {}
    return {f["properties"]["seg_id"]: shape(f["geometry"])
            for f in json.load(open(path))["features"]}


def main():
    massdot = json.load(open(DATA / "massdot_roadinv_raw.geojson"))["features"]
    osm = load_osm_ways()
    boundary = build_boundary()
    boundary_m = transform(TO_M, boundary)
    edits = load_edits()
    custom_geom = load_custom_geometry()

    out = []
    massdot_by_name = {}

    for i, f in enumerate(massdot):
        p = f["properties"]
        seg_id = f"S{i:03d}"
        geom = custom_geom.get(seg_id) or shape(f["geometry"])
        geom_m = transform(TO_M, geom)
        if geom_m.length < 5:
            continue
        name = NAME_FIXES.get(p.get("St_Name") or "", p.get("St_Name") or "")
        named = bool(name)
        jur = JURISDICTION.get(str(p["Jurisdictn"]) if p["Jurisdictn"] is not None else None, "unknown")
        surf = SURFACE.get(str(p["Surface_Tp"]) if p["Surface_Tp"] is not None else None, "unknown")

        if not name:
            mid = geom_m.interpolate(0.5, normalized=True)
            best, best_d = None, 40.0
            for w in osm:
                dd = w["geom_m"].distance(mid)
                if dd < best_d:
                    best, best_d = w, dd
            name = osm_label(best) if best else "(unidentified)"

        required = (
            jur in ("town", "MassDOT", "DCR", "unknown") or (jur == "unaccepted/private" and named)
        ) and name != "NET TRAIL"
        if seg_id in RENAMES:
            name, required = RENAMES[seg_id]
        if seg_id in QUABBIN_EXCLUDE:
            required = False
        if seg_id in edits["require_segments"]:
            required = True
        if seg_id in edits["exclude_segments"]:
            required = False
        if seg_id in custom_geom:
            print(f"  custom geometry: {seg_id} {name}")

        cat = "trail" if p.get("St_Name") == "NET TRAIL" else category(name, named, jur)
        if named:
            massdot_by_name.setdefault(name.upper(), []).append(geom_m)

        out.append({
            "type": "Feature",
            "properties": {
                "seg_id": seg_id, "name": name, "source": "massdot",
                "named_in_massdot": named, "jurisdiction": jur, "surface": surf,
                "category": cat, "required": required,
                "length_mi": round(geom_m.length / 1609.344, 3),
            },
            "geometry": geom.__geo_interface__,
        })

    # OSM supplements
    for sup_name, cfg in SUPPLEMENTS.items():
        parts = []
        for w in osm:
            if (w["tags"].get("name") or "").upper() != sup_name \
                    and w["osm_id"] not in cfg.get("way_ids", []):
                continue
            g = w["geom_m"].intersection(boundary_m)
            if g.is_empty:
                continue
            parts.append(g)
        if not parts:
            print(f"WARNING: no OSM ways for supplement {sup_name}")
            continue
        merged = unary_union(parts)
        if "prepend_from" in cfg:
            start_m = transform(TO_M, LineString([cfg["prepend_from"]] * 2)).coords[0]
            line = merged if isinstance(merged, LineString) else max(merged.geoms, key=lambda g: g.length)
            c = list(line.coords)
            if ((c[0][0] - start_m[0]) ** 2 + (c[0][1] - start_m[1]) ** 2) > \
               ((c[-1][0] - start_m[0]) ** 2 + (c[-1][1] - start_m[1]) ** 2):
                c = c[::-1]
            merged = LineString([start_m] + c)
        if cfg["extend"]:
            existing = unary_union(
                [g for k, gs in massdot_by_name.items() if sup_name in k for g in gs]
            )
            if not existing.is_empty:
                merged = merged.difference(existing.buffer(30))
        if merged.is_empty:
            continue
        geoms = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
        for j, g in enumerate(geoms):
            if g.length < 15:
                continue
            xid = f"X{len(out):03d}"
            req = cfg["required"]
            if xid in edits["require_segments"]:
                req = True
            if xid in edits["exclude_segments"]:
                req = False
            out.append({
                "type": "Feature",
                "properties": {
                    "seg_id": xid,
                    "name": sup_name + (" (beyond massdot)" if cfg["extend"] else ""),
                    "source": "osm", "named_in_massdot": False,
                    "jurisdiction": cfg["jurisdiction"], "surface": "unknown",
                    "category": "road", "required": req,
                    "length_mi": round(g.length / 1609.344, 3),
                },
                "geometry": transform(TO_DEG, g).__geo_interface__,
            })

    with open(DATA / "roads.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": out}, f)

    # CityStrides-style collectible points: every 25 m along required segments.
    # Ids are "<seg_id>-<index>", stable while the segment geometry is unchanged.
    SPACING = 25.0
    points, excluded = [], 0
    skip = set(edits["exclude_points"])
    for o in out:
        p = o["properties"]
        if not p["required"]:
            continue
        g = transform(TO_M, shape(o["geometry"]))
        n = max(2, int(g.length // SPACING) + 1)
        for k in range(n):
            pid = f"{p['seg_id']}-{k}"
            if pid in skip:
                excluded += 1
                continue
            pt = transform(TO_DEG, g.interpolate(k / (n - 1), normalized=True))
            points.append({
                "id": pid, "seg_id": p["seg_id"], "name": p["name"],
                "lon": round(pt.x, 6), "lat": round(pt.y, 6),
            })
    with open(DATA / "points.json", "w") as f:
        json.dump(points, f)
    print(f"{len(points)} collectible points (25 m spacing on required roads, "
          f"{excluded} hand-excluded)")

    req = [o["properties"] for o in out if o["properties"]["required"]]
    opt = [o["properties"] for o in out if not o["properties"]["required"]]
    print(f"{len(out)} segments; required {len(req)} ({sum(p['length_mi'] for p in req):.2f} mi), "
          f"optional {len(opt)} ({sum(p['length_mi'] for p in opt):.2f} mi)")
    for p in out:
        pp = p["properties"]
        if pp["source"] == "osm":
            print(f"  supplement: {pp['seg_id']} {pp['name']} {pp['length_mi']} mi (required={pp['required']})")


if __name__ == "__main__":
    main()
