"""Build map.html — the canonical Shutesbury every-road map.

Self-contained (data inlined): FRCOG Map 3 overlay, MassDOT-derived road
inventory, and 3k+ collectible points on required roads. Upload GPX file(s)
in the browser to color points green (collected, within 25 m) / red (missed)
and get per-road completion stats. Needs internet only for basemap tiles
and Leaflet CDN.

Usage: uv run make_map.py [--out map.html]
"""

import argparse
import base64
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>All of Shutesbury</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body { margin: 0; height: 100%; font-family: system-ui, sans-serif; }
  #map { position: absolute; inset: 0; }
  #panel {
    position: absolute; top: 10px; right: 10px; z-index: 1000; width: 300px;
    background: rgba(255,255,255,.96); border-radius: 8px; padding: 12px 14px;
    box-shadow: 0 1px 6px rgba(0,0,0,.3); font-size: 13px; max-height: calc(100% - 40px);
    overflow-y: auto;
  }
  #panel h1 { font-size: 15px; margin: 0 0 8px; }
  #panel h2 { font-size: 13px; margin: 12px 0 4px; }
  #stats .big { font-size: 22px; font-weight: 700; }
  #roadlist { width: 100%; border-collapse: collapse; }
  #roadlist td { padding: 1px 4px; border-bottom: 1px solid #eee; }
  #roadlist td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
  #roadlist tr.done td { color: #999; }
  label { display: block; margin: 4px 0; }
  input[type=range] { width: 130px; vertical-align: middle; }
  .hint { color: #777; font-size: 11px; }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h1>All of Shutesbury</h1>
  <label>Ride GPX: <input type="file" id="gpx" accept=".gpx" multiple></label>
  <div class="hint">Points on required roads; a point is collected when a track
  passes within <span id="radlabel">25</span> m.</div>
  <label>Radius <input type="range" id="radius" min="10" max="50" value="25" step="5"></label>
  <label>Town map overlay <input type="range" id="overlayop" min="0" max="100" value="65"></label>
  <label><input type="checkbox" id="editmode"> Edit mode (click points to exclude)</label>
  <div id="editbar" style="display:none">
    <span id="editcount" class="hint"></span>
    <button id="exportedits">Download edits.json</button>
    <div class="hint">Put the file next to build_roads.py, then rerun
    build_roads.py + make_map.py to bake edits in.</div>
  </div>
  <div id="stats"></div>
  <div id="roads"></div>
  <div style="margin-top:10px; border-top:1px solid #ddd; padding-top:8px" class="hint">
    Ride every road in Shutesbury, MA — 3,078 points on 46 required miles.
    Upload your ride's GPX above to see how you did.<br>
    Routes that do it all: <a href="route_conservative.gpx" download>conservative
    (76.8 mi)</a> · <a href="route_wide.gpx" download>trusting (76.0 mi)</a> ·
    <a href="friend_ride.gpx" download>the 84.5% attempt</a><br>
    <a href="https://github.com/andyreagan/all-of-shutesbury">data + methodology</a>
  </div>
</div>
<script>
const ROADS = __ROADS__;
const BOUNDARY = __BOUNDARY__;
const POINTS = __POINTS__;
const EDITS = __EDITS__;
const OVERLAY_BOUNDS = __OVERLAY_BOUNDS__;
const OVERLAY_PNG = "__OVERLAY_PNG__";

const map = L.map('map').setView([42.459, -72.429], 13);
const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(map);
const topo = L.tileLayer(
  'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 16, attribution: 'USGS' });

const overlay = L.imageOverlay(OVERLAY_PNG,
  [[OVERLAY_BOUNDS.south, OVERLAY_BOUNDS.west], [OVERLAY_BOUNDS.north, OVERLAY_BOUNDS.east]],
  { opacity: 0.65 }).addTo(map);

L.geoJSON(BOUNDARY, { style: { color: '#000', weight: 2, dashArray: '8 4', fill: false } }).addTo(map);

const reqStyle = { color: '#555', weight: 2, opacity: 0.9 };
const optStyle = { color: '#b8860b', weight: 1.5, opacity: 0.7, dashArray: '4 6' };
const reqRoads = L.layerGroup(), optRoads = L.layerGroup();
for (const f of ROADS.features) {
  const p = f.properties;
  const lyr = L.geoJSON(f, { style: p.required ? reqStyle : optStyle });
  lyr.bindTooltip(`<b>${p.name}</b> (${p.seg_id})<br>${p.length_mi} mi — ` +
    `${p.jurisdiction}, ${p.surface}${p.required ? '' : ' — optional'}`, { sticky: true });
  (p.required ? reqRoads : optRoads).addLayer(lyr);
}
reqRoads.addTo(map); optRoads.addTo(map);

const canvas = L.canvas({ padding: 0.3 });
const ptLayer = L.layerGroup().addTo(map);
const sessionExcluded = new Set();  // point ids excluded by hand this session
const markers = POINTS.map((pt, i) => {
  const m = L.circleMarker([pt.lat, pt.lon], {
    renderer: canvas, radius: 3, stroke: false, fillColor: '#888', fillOpacity: 0.85,
  });
  m.bindTooltip(() => `${pt.name}<br><span style="color:#777">${pt.id}` +
    `${sessionExcluded.has(pt.id) ? ' — EXCLUDED' : ''}</span>`, { sticky: true });
  m.on('click', () => {
    if (!document.getElementById('editmode').checked) return;
    if (sessionExcluded.has(pt.id)) sessionExcluded.delete(pt.id);
    else sessionExcluded.add(pt.id);
    styleMarker(i);
    updateEditBar();
    recompute();
  });
  ptLayer.addLayer(m);
  return m;
});
const hitState = new Array(POINTS.length).fill(null); // null until a GPX is loaded
function styleMarker(i) {
  const m = markers[i];
  if (sessionExcluded.has(POINTS[i].id)) {
    m.setStyle({ fillColor: '#222', fillOpacity: 0.9 }); m.setRadius(5);
  } else if (hitState[i] === null) {
    m.setStyle({ fillColor: '#888', fillOpacity: 0.85 }); m.setRadius(3);
  } else if (hitState[i]) {
    m.setStyle({ fillColor: '#1a9c2f', fillOpacity: 0.6 }); m.setRadius(2.5);
  } else {
    m.setStyle({ fillColor: '#e02020', fillOpacity: 0.95 }); m.setRadius(4);
  }
}
function updateEditBar() {
  const n = sessionExcluded.size + EDITS.exclude_points.length;
  document.getElementById('editcount').textContent =
    `${sessionExcluded.size} excluded this session (${n} total incl. baked-in)`;
}
document.getElementById('editmode').addEventListener('change', e => {
  document.getElementById('editbar').style.display = e.target.checked ? 'block' : 'none';
  updateEditBar();
});
document.getElementById('exportedits').addEventListener('click', () => {
  const out = { ...EDITS,
    exclude_points: [...new Set([...EDITS.exclude_points, ...sessionExcluded])].sort() };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)],
    { type: 'application/json' }));
  a.download = 'edits.json';
  a.click();
});

let gpxTrackLayer = null;
L.control.layers(
  { OSM: osm, 'USGS Topo': topo },
  { 'Town map (FRCOG 2004)': overlay, 'Required roads': reqRoads,
    'Optional roads': optRoads, 'Points': ptLayer },
  { collapsed: false }).addTo(map);

document.getElementById('overlayop').addEventListener('input', e =>
  overlay.setOpacity(e.target.value / 100));

// --- coverage ---
const LAT0 = 42.459;
const MX = 111320 * Math.cos(LAT0 * Math.PI / 180), MY = 110950;
const toM = (lat, lon) => [lon * MX, lat * MY];

let tracks = [];   // array of arrays of [x, y] (meters)
let trackPtsRaw = [];  // latlngs per file for drawing

function recompute() {
  const R = +document.getElementById('radius').value;
  document.getElementById('radlabel').textContent = R;
  if (!tracks.length) return;

  // grid-hash track sub-segments
  const CELL = 100;
  const grid = new Map();
  for (const t of tracks) {
    for (let i = 0; i + 1 < t.length; i++) {
      const [x1, y1] = t[i], [x2, y2] = t[i + 1];
      if (Math.hypot(x2 - x1, y2 - y1) > 500) continue; // GPS gap, don't bridge
      const cx0 = Math.floor((Math.min(x1, x2) - R) / CELL), cx1 = Math.floor((Math.max(x1, x2) + R) / CELL);
      const cy0 = Math.floor((Math.min(y1, y2) - R) / CELL), cy1 = Math.floor((Math.max(y1, y2) + R) / CELL);
      for (let cx = cx0; cx <= cx1; cx++) for (let cy = cy0; cy <= cy1; cy++) {
        const k = cx + ':' + cy;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push([x1, y1, x2, y2]);
      }
    }
  }
  const distSeg = (px, py, x1, y1, x2, y2) => {
    const dx = x2 - x1, dy = y2 - y1;
    const L2 = dx * dx + dy * dy;
    let t = L2 ? ((px - x1) * dx + (py - y1) * dy) / L2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  };

  const perRoad = new Map();
  let got = 0, active = 0;
  POINTS.forEach((pt, i) => {
    const [x, y] = toM(pt.lat, pt.lon);
    const k = Math.floor(x / CELL) + ':' + Math.floor(y / CELL);
    let hit = false;
    for (const s of (grid.get(k) || [])) {
      if (distSeg(x, y, s[0], s[1], s[2], s[3]) <= R) { hit = true; break; }
    }
    hitState[i] = hit;
    styleMarker(i);
    if (sessionExcluded.has(pt.id)) return;  // excluded points don't count
    active++;
    if (hit) got++;
    if (!perRoad.has(pt.name)) perRoad.set(pt.name, { got: 0, total: 0 });
    const r = perRoad.get(pt.name);
    r.total++; if (hit) r.got++;
  });

  // a road is done at >= 95% of its points (ceil'd: short roads need 100%)
  const ROAD_T = 0.95;
  const rows = [...perRoad.entries()]
    .map(([name, r]) => ({ name, ...r, miss: r.total - r.got,
      done: r.got >= Math.ceil(ROAD_T * r.total) }))
    .sort((a, b) => (a.done - b.done) || (b.miss - a.miss) || a.name.localeCompare(b.name));
  const nDone = rows.filter(r => r.done).length;

  const pct = (100 * got / active).toFixed(1);
  document.getElementById('stats').innerHTML =
    `<h2>Result</h2><span class="big">${pct}%</span> — ${got}/${active} points` +
    `<br>Roads done (&ge;95% of points): <b>${nDone}/${rows.length}</b>` +
    `<br>${nDone === rows.length ? '&#127942; TOWN COMPLETE'
      : (rows.length - nDone) + ' roads to go'}`;

  document.getElementById('roads').innerHTML = '<h2>By road</h2><table id="roadlist">' +
    rows.map(r => `<tr class="${r.done ? 'done' : ''}"><td>${r.name}</td>` +
      `<td>${r.done ? '&#10003;' : r.got + '/' + r.total}</td></tr>`).join('') + '</table>';
}

document.getElementById('radius').addEventListener('change', recompute);

document.getElementById('gpx').addEventListener('change', async e => {
  tracks = []; trackPtsRaw = [];
  for (const file of e.target.files) {
    const xml = new DOMParser().parseFromString(await file.text(), 'application/xml');
    for (const seg of xml.querySelectorAll('trkseg')) {
      const t = [], raw = [];
      for (const p of seg.querySelectorAll('trkpt')) {
        const lat = +p.getAttribute('lat'), lon = +p.getAttribute('lon');
        t.push(toM(lat, lon)); raw.push([lat, lon]);
      }
      if (t.length > 1) { tracks.push(t); trackPtsRaw.push(raw); }
    }
  }
  if (gpxTrackLayer) map.removeLayer(gpxTrackLayer);
  gpxTrackLayer = L.layerGroup(trackPtsRaw.map(r =>
    L.polyline(r, { color: '#2255cc', weight: 2, opacity: 0.5 }))).addTo(map);
  recompute();
});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="map.html")
    args = ap.parse_args()

    roads = json.load(open(DATA / "roads.geojson"))
    boundary = json.load(open(DATA / "boundary.geojson"))
    points = json.load(open(DATA / "points.json"))
    cal = json.load(open(DATA / "map3_calibration.json"))
    png_b64 = base64.b64encode((DATA / "map3_overlay.png").read_bytes()).decode()
    edits = {"require_segments": [], "exclude_segments": [], "exclude_points": []}
    edits_path = Path(__file__).parent / "edits.json"
    if edits_path.exists():
        edits.update(json.load(open(edits_path)))

    html = (
        TEMPLATE
        .replace("__ROADS__", json.dumps(roads))
        .replace("__BOUNDARY__", json.dumps(boundary))
        .replace("__POINTS__", json.dumps(points))
        .replace("__EDITS__", json.dumps(edits))
        .replace("__OVERLAY_BOUNDS__", json.dumps(cal["overlay_bounds"]))
        .replace("__OVERLAY_PNG__", "data:image/png;base64," + png_b64)
    )
    Path(args.out).write_text(html)
    print(f"wrote {args.out} ({len(html)//1024} KB, {len(points)} points)")


if __name__ == "__main__":
    main()
