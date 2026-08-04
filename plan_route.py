"""Plan an every-road route: Rural Postman over the required network.

Usage: uv run plan_route.py [--policy wide|intown] [--out route.gpx] [--elevation]

- required edges: every required segment in data/roads.geojson
- connectors: optional segments, plus (policy=wide) all OSM roads within ~2 km
  of town (data/osm_connectors_raw.json), plus local-knowledge links from
  README routing notes (Carver chain, Sirius<->Farmhouse)
- solve: connect required components via cheapest paths, even out odd-degree
  nodes via min-weight matching on shortest paths, Euler circuit from Town Hall
- report: distance, deadhead, U-turns, (optionally) elevation gain
"""

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree
from shapely.ops import transform

DATA = Path(__file__).parent / "data"
TO_M = Transformer.from_crs(4326, 26986, always_xy=True).transform
TO_DEG = Transformer.from_crs(26986, 4326, always_xy=True).transform
TOWN_HALL = transform(TO_M, Point(-72.40959, 42.45182))

SNAP = 10.0          # node identity grid (m)
JUNCTION_TOL = 30.0  # endpoint-to-edge distance that implies a junction
DANGLE_MAX = 400.0   # max virtual connector for a dangling required endpoint
# local knowledge: connect these roads' nearest endpoints (README routing notes)
# (a, b, max_link_m) — Carver is "basically a straight shot between the two sides"
KNOWN_LINKS = [
    ("CARVER ROAD", "CARVER ROAD WEST", 1300),
    ("CARVER ROAD", "CARVER ROAD EAST", 600),
    ("CARVER ROAD WEST", "CARVER ROAD EAST", 1300),
    ("SIRIUS COMMUNITY CENTER DRIVE", "FARMHOUSE DRIVE", 600),
]
# dangle-fixes >= this length are speculative; --conservative drops them
SPECULATIVE = 100.0
CONSERVATIVE_ALLOW = {"NEW BOSTON ROAD"}  # user-blessed: Jennison via north side
COST = {"required": 1.0, "road": 1.0, "trail": 1.5, "track": 1.5, "virtual": 1.3,
        "driveway": 2.0, "osm_road": 1.0, "osm_track": 1.6, "osm_service": 1.8}


def load_edges(policy):
    edges = []  # dicts: geom (m), kind, name
    roads = json.load(open(DATA / "roads.geojson"))["features"]
    for f in roads:
        p = f["properties"]
        g = transform(TO_M, shape(f["geometry"]))
        if p["required"]:
            kind = "required"
        else:
            c = p["category"]
            kind = {"road": "road", "trail": "trail", "trail/track": "track",
                    "driveway": "driveway"}.get(c, "track")
        edges.append({"geom": g, "kind": kind, "name": p["name"], "seg": p["seg_id"]})

    if policy == "wide":
        osm = json.load(open(DATA / "osm_connectors_raw.json"))["elements"]
        # split OSM ways at coords shared by >=2 ways (junction nodes share coords)
        counts = {}
        for e in osm:
            for pt in e.get("geometry", []):
                k = (round(pt["lon"], 6), round(pt["lat"], 6))
                counts[k] = counts.get(k, 0) + 1
        for e in osm:
            geom = e.get("geometry", [])
            if len(geom) < 2:
                continue
            hw = e["tags"].get("highway")
            kind = ("osm_road" if hw in ("primary", "secondary", "tertiary",
                                         "unclassified", "residential")
                    else "osm_service" if hw == "service" else "osm_track")
            coords, name = [], e["tags"].get("name", f"osm:{hw}")
            for i, pt in enumerate(geom):
                coords.append((pt["lon"], pt["lat"]))
                k = (round(pt["lon"], 6), round(pt["lat"], 6))
                if 0 < i < len(geom) - 1 and counts[k] > 1 and len(coords) > 1:
                    edges.append({"geom": transform(TO_M, LineString(coords)),
                                  "kind": kind, "name": name, "seg": None})
                    coords = [coords[-1]]
            if len(coords) > 1:
                edges.append({"geom": transform(TO_M, LineString(coords)),
                              "kind": kind, "name": name, "seg": None})
    return edges


def split_at_junctions(edges):
    """Split any edge whose interior passes within JUNCTION_TOL of another
    edge's endpoint, at the projection point."""
    endpoints = []
    for i, e in enumerate(edges):
        c = list(e["geom"].coords)
        endpoints.append((Point(c[0]), i))
        endpoints.append((Point(c[-1]), i))
    tree = STRtree([p for p, _ in endpoints])
    out = []
    for i, e in enumerate(edges):
        g = e["geom"]
        cuts = set()
        for j in tree.query(g.buffer(JUNCTION_TOL)):
            pt, owner = endpoints[j]
            if owner == i or g.distance(pt) > JUNCTION_TOL:
                continue
            d = g.project(pt)
            if 15.0 < d < g.length - 15.0:
                cuts.add(round(d, 1))
        if not cuts:
            out.append(e)
            continue
        prev = 0.0
        for d in sorted(cuts) + [g.length]:
            n = max(2, int((d - prev) // 25) + 1)
            pts = [g.interpolate(prev + (d - prev) * k / (n - 1)) for k in range(n)]
            piece = LineString(pts)
            if piece.length > 1:
                out.append({**e, "geom": piece})
            prev = d
    return out


def node_of(pt, nodes):
    k = (round(pt[0] / SNAP), round(pt[1] / SNAP))
    if k not in nodes:
        nodes[k] = pt
    return k


def build_graph(edges):
    G = nx.MultiGraph()
    nodes = {}
    for e in edges:
        c = list(e["geom"].coords)
        u, v = node_of(c[0], nodes), node_of(c[-1], nodes)
        if u == v and e["geom"].length < 30:
            continue
        G.add_edge(u, v, geom=e["geom"], kind=e["kind"], name=e["name"],
                   length=e["geom"].length,
                   weight=e["geom"].length * COST[e["kind"]])
    return G, nodes


def add_virtual_links(G, nodes, edges, conservative=False):
    # named local-knowledge links
    by_name = {}
    for e in edges:
        if e["kind"] == "required":
            by_name.setdefault(e["name"], []).append(e["geom"])
    for a, b, cap in KNOWN_LINKS:
        if a not in by_name or b not in by_name:
            continue
        best = None
        for ga in by_name[a]:
            for gb in by_name[b]:
                for pa in (ga.coords[0], ga.coords[-1]):
                    for pb in (gb.coords[0], gb.coords[-1]):
                        d = math.dist(pa, pb)
                        if best is None or d < best[0]:
                            best = (d, pa, pb)
        d, pa, pb = best
        if d > cap:
            print(f"  skip link {a}<->{b}: {d:.0f} m apart")
            continue
        u, v = node_of(pa, nodes), node_of(pb, nodes)
        if u != v and not G.has_edge(u, v):
            G.add_edge(u, v, geom=LineString([pa, pb]), kind="virtual",
                       name=f"link {a}<->{b}", length=d, weight=d * COST["virtual"])
            print(f"  link {a}<->{b}: {d:.0f} m")

    # dangling required endpoints -> project onto nearest other edge
    all_edges = list(G.edges(keys=True, data=True))
    geoms = [d["geom"] for *_, d in all_edges]
    tree = STRtree(geoms)
    for n in list(G.nodes):
        inc = list(G.edges(n, data=True))
        if len(inc) != 1 or inc[0][2]["kind"] != "required":
            continue
        pt = Point(nodes[n])
        best = None
        for j in tree.query(pt.buffer(DANGLE_MAX)):
            u, v, k, d = all_edges[j]
            g = d["geom"]
            if (u == n or v == n) or g.distance(pt) < 1:
                continue
            dd = g.distance(pt)
            if dd < 15:
                continue  # will snap anyway
            if best is None or dd < best[0]:
                best = (dd, g.interpolate(g.project(pt)))
        if best and best[0] < DANGLE_MAX:
            dd, proj = best
            if conservative and dd >= SPECULATIVE \
                    and inc[0][2]["name"] not in CONSERVATIVE_ALLOW:
                print(f"  conservative: no dangle-fix for {inc[0][2]['name']} ({dd:.0f} m)")
                continue
            m = node_of((proj.x, proj.y), nodes)
            if m != n:
                G.add_edge(n, m, geom=LineString([nodes[n], (proj.x, proj.y)]),
                           kind="virtual", name=f"dangle-fix {inc[0][2]['name']}",
                           length=dd, weight=dd * COST["virtual"])
                print(f"  dangle-fix {inc[0][2]['name']}: {dd:.0f} m")


def solve(G, start):
    R = nx.MultiGraph()
    for u, v, k, d in G.edges(keys=True, data=True):
        if d["kind"] == "required":
            R.add_edge(u, v, **d)
    print(f"required graph: {R.number_of_edges()} edges, "
          f"{nx.number_connected_components(R)} components")

    # connect components via cheapest paths in G
    comps = [set(c) for c in nx.connected_components(R)]
    main = max(comps, key=len)
    for comp in comps:
        if comp is main:
            continue
        dist, paths = nx.multi_source_dijkstra(G, comp, weight="weight")
        best = min((n for n in main if n in dist), key=lambda n: dist[n], default=None)
        if best is None:
            sys.exit(f"cannot connect component of size {len(comp)}")
        path = paths[best]
        for a, b in zip(path, path[1:]):
            d = min(G[a][b].values(), key=lambda d: d["weight"])
            R.add_edge(a, b, **d)
        main |= comp
    # matching may also reconnect; recompute odd nodes on connected R
    odd = [n for n in R.nodes if R.degree(n) % 2 == 1]
    print(f"{len(odd)} odd-degree nodes")
    dists, paths = {}, {}
    for o in odd:
        dists[o], paths[o] = nx.single_source_dijkstra(G, o, weight="weight")
    K = nx.Graph()
    for i, a in enumerate(odd):
        for b in odd[i + 1:]:
            if b in dists[a]:
                K.add_edge(a, b, weight=dists[a][b])
    match = nx.min_weight_matching(K)
    for a, b in match:
        path = paths[a][b]
        for u, v in zip(path, path[1:]):
            d = min(G[u][v].values(), key=lambda d: d["weight"])
            R.add_edge(u, v, **d)

    start_node = min(R.nodes, key=lambda n: math.dist(n_xy[n], (TOWN_HALL.x, TOWN_HALL.y)))
    circuit = list(nx.eulerian_circuit(R, source=start_node, keys=True))
    return R, circuit


def main():
    global n_xy
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["wide", "intown"], default="wide")
    ap.add_argument("--out", default=None)
    ap.add_argument("--elevation", action="store_true")
    ap.add_argument("--conservative", action="store_true",
                    help="drop speculative (>=100 m) unverified dangle-fixes")
    args = ap.parse_args()
    out = args.out or ("route_conservative.gpx" if args.conservative
                       else f"route_{args.policy}.gpx")

    edges = load_edges(args.policy)
    print(f"{len(edges)} raw edges ({args.policy})")
    edges = split_at_junctions(edges)
    print(f"{len(edges)} after junction splitting")
    G, nodes = build_graph(edges)
    n_xy = nodes
    add_virtual_links(G, nodes, edges, conservative=args.conservative)
    R, circuit = solve(G, TOWN_HALL)

    # assemble geometry
    coords = []
    uturns = 0
    prev = None
    total = 0.0
    used_virtual = {}
    for u, v, k in circuit:
        d = R[u][v][k]
        total += d["length"]
        c = list(d["geom"].coords)
        if math.dist(c[0], nodes[u]) > math.dist(c[-1], nodes[u]):
            c = c[::-1]
        if prev is not None and (v, u) == prev:  # left the way we came in
            uturns += 1
        prev = (u, v)
        if d["kind"] == "virtual":
            used_virtual[d["name"]] = used_virtual.get(d["name"], 0) + 1
        coords.extend(c if not coords else c[1:])
    if used_virtual:
        print("virtual links used (verify these are actually rideable):")
        for name, n in sorted(used_virtual.items()):
            print(f"  {n}x {name}")

    req_unique = sum(d["length"] for *_, d in G.edges(keys=True, data=True)
                     if d["kind"] == "required")
    mi = total / 1609.344
    print(f"\nROUTE ({args.policy}): {mi:.1f} mi total, "
          f"{req_unique/1609.344:.1f} mi unique required, "
          f"{(total-req_unique)/1609.344:.1f} mi repeated/connector "
          f"({100*(total-req_unique)/total:.0f}% overhead)")
    print(f"U-turns (immediate backtracks): {uturns}")

    lonlat = [TO_DEG(x, y) for x, y in coords]
    eles = None
    if args.elevation:
        eles = fetch_elevation(lonlat)
        if eles:
            gain = ascent(eles)
            print(f"elevation gain: {gain:.0f} m ({gain*3.281:.0f} ft)")

    with open(out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="all-of-shutesbury" '
                'xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write(f' <trk><name>All of Shutesbury ({args.policy})</name><trkseg>\n')
        for i, (lon, lat) in enumerate(lonlat):
            ele = f"<ele>{eles[i]:.1f}</ele>" if eles else ""
            f.write(f'  <trkpt lat="{lat:.6f}" lon="{lon:.6f}">{ele}</trkpt>\n')
        f.write(' </trkseg></trk>\n</gpx>\n')
    print(f"wrote {out} ({len(lonlat)} points)")


def fetch_elevation(lonlat, step=5):
    pts = lonlat[::step]
    eles = []
    try:
        for i in range(0, len(pts), 100):
            chunk = pts[i:i + 100]
            url = ("https://api.open-meteo.com/v1/elevation?latitude="
                   + ",".join(f"{lat:.5f}" for _, lat in chunk)
                   + "&longitude=" + ",".join(f"{lon:.5f}" for lon, _ in chunk))
            with urllib.request.urlopen(url, timeout=30) as r:
                eles.extend(json.load(r)["elevation"])
    except Exception as ex:
        print(f"elevation fetch failed ({ex}); skipping")
        return None
    # expand back to full resolution by interpolation
    full = []
    for i in range(len(lonlat)):
        j = min(i / step, len(eles) - 1)
        a, b = int(j), min(int(j) + 1, len(eles) - 1)
        full.append(eles[a] + (eles[b] - eles[a]) * (j - a))
    return full


def ascent(eles, window=9):
    sm = [sum(eles[max(0, i - window // 2):i + window // 2 + 1])
          / len(eles[max(0, i - window // 2):i + window // 2 + 1])
          for i in range(len(eles))]
    return sum(max(0.0, b - a) for a, b in zip(sm, sm[1:]))


if __name__ == "__main__":
    main()
