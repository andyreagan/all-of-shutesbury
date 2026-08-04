"""Score a GPX route against the Shutesbury collectible points
(CityStrides-style: a point is collected when the track passes within
--radius meters of it; same model as map.html).

A road is DONE when >= --road-threshold of its points are collected
(ceil'd, so roads under ~20 points still need 100%). Town complete =
every required road done.

Usage:  uv run check_route.py ROUTE.gpx [more.gpx ...] [--radius 25]
        [--road-threshold 0.95] [--json-out r.json]
"""

import math

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform, unary_union
from shapely.prepared import prep

DATA = Path(__file__).parent / "data"
TO_M = Transformer.from_crs(4326, 26986, always_xy=True).transform

TRKPT_RE = re.compile(r'<trkpt\s+lat="([-\d.]+)"\s+lon="([-\d.]+)"')


def load_gpx_lines(paths):
    lines = []
    for path in paths:
        text = Path(path).read_text()
        for seg in re.split(r"</trkseg>", text):
            pts = [(float(lon), float(lat)) for lat, lon in TRKPT_RE.findall(seg)]
            if len(pts) >= 2:
                lines.append(transform(TO_M, LineString(pts)))
    if not lines:
        sys.exit(f"no track points found in {paths}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpx", nargs="+")
    ap.add_argument("--radius", type=float, default=25.0, help="meters")
    ap.add_argument("--road-threshold", type=float, default=0.95,
                    help="fraction of a road's points needed to call it done")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    points = json.load(open(DATA / "points.json"))
    buffered = prep(unary_union(load_gpx_lines(args.gpx)).buffer(args.radius))

    per_road = defaultdict(lambda: [0, 0])  # got, total
    for pt in points:
        hit = buffered.contains(transform(TO_M, Point(pt["lon"], pt["lat"])))
        pt["collected"] = hit
        per_road[pt["name"]][1] += 1
        if hit:
            per_road[pt["name"]][0] += 1

    got = sum(1 for p in points if p["collected"])
    total = len(points)
    done = {name: g >= math.ceil(args.road_threshold * t)
            for name, (g, t) in per_road.items()}
    n_done = sum(done.values())
    print(f"{got}/{total} points collected ({100*got/total:.1f}%)")
    print(f"roads done (>= {100*args.road_threshold:.0f}% of points, ceil'd): "
          f"{n_done}/{len(per_road)}")
    print("VERDICT:", "TOWN COMPLETE" if n_done == len(per_road)
          else f"INCOMPLETE ({len(per_road)-n_done} roads to go)\n")

    missing = sorted(
        ((name, g, t) for name, (g, t) in per_road.items() if not done[name]),
        key=lambda x: x[1] - x[2],
    )
    for name, g, t in missing:
        need = math.ceil(args.road_threshold * t)
        km = (t - g) * 25 / 1000
        print(f"  {name:40s} {g:4d}/{t:4d} (need {need})  ~{km:.1f} km missing")

    if args.json_out:
        json.dump(points, open(args.json_out, "w"))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
