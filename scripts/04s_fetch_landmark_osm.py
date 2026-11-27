"""Download OpenStreetMap shapes around each v19 landmark (Phase 0 of
docs/landmarks_plan.md).

04g_fetch_osm.py fetches only buildings tagged with a colour or material,
for wall paint. The landmark models need the other tags mappers record on
landmarks: building:part outlines with height, min_height, roof:shape,
roof:colour and building:levels (OSM's Simple 3D Buildings scheme), towers,
masts and spires, and bridge supports and structures. These are one
dimension source among several; every value a model uses is still cited in
its dossier (config/landmarks/<slug>.json).

Within RADIUS_M of each point in config/landmarks/index.json (BRIDGE_RADIUS_M
for bridges, which are long), the query takes:
  - every building:part;
  - buildings with height, roof:shape, building:levels or a name;
  - man_made=tower|mast|spire|bridge, and bridge:support / bridge:structure;
  - bridge ways (bridge=*) for the bridge entries.
04g_fetch_osm.py is unchanged, so region builds stay byte-identical.

Writes data/raw/landmarks_osm.json (one Overpass response, immutable) and
output/landmarks/osm_parts_summary.json (per slug: counts of parts and of the
tags above). License: ODbL 1.0; credit "© OpenStreetMap contributors".

Usage: uv run python scripts/04s_fetch_landmark_osm.py
"""

import json
import math

from pixelphilly.landmark_dossier import BRIDGE_KITS
from pixelphilly.projection import REPO_ROOT
from pixelphilly.sources import RAW, fetch_overpass

INDEX = REPO_ROOT / "config" / "landmarks" / "index.json"
RADIUS_M = 250
BRIDGE_RADIUS_M = 400
OUT_NAME = "landmarks_osm.json"
SUMMARY = REPO_ROOT / "output" / "landmarks" / "osm_parts_summary.json"
TAGS = ("height", "min_height", "roof:shape", "roof:colour", "roof:height", "building:colour", "building:levels")


def radius(entry):
    return BRIDGE_RADIUS_M if entry["kit"] in BRIDGE_KITS else RADIUS_M


def query_for(entries):
    sel = []
    for e in entries:
        a = f"around:{radius(e)},{e['lat']},{e['lon']}"
        sel += [f'nwr["building:part"]({a});', f'nwr["building"]["height"]({a});',
                f'nwr["building"]["roof:shape"]({a});', f'nwr["building"]["building:levels"]({a});',
                f'nwr["building"]["name"]({a});', f'nwr["man_made"~"^(tower|mast|spire|bridge)$"]({a});',
                f'nwr["bridge:support"]({a});', f'nwr["bridge:structure"]({a});']
        if e["kit"] in BRIDGE_KITS:
            sel.append(f'way["bridge"]["bridge"!="no"]({a});')
    return f'[out:json][timeout:300];({"".join(sel)});out tags geom;'


def center(el):
    """Mean of an element's geometry points (ways, relations' members) or the node."""
    pts = []
    if "geometry" in el:
        pts = [(p["lon"], p["lat"]) for p in el["geometry"] if p]
    for m in el.get("members", []):
        pts += [(p["lon"], p["lat"]) for p in m.get("geometry", []) if p]
    if "lon" in el:
        pts.append((el["lon"], el["lat"]))
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def dist_m(lon1, lat1, lon2, lat2):
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * 111320 * k, (lat2 - lat1) * 110574)


def summarize(elements, entries):
    """Per slug: elements whose center is within that entry's radius."""
    out = {}
    for e in entries:
        near = []
        for el in elements:
            c = center(el)
            if c and dist_m(e["lon"], e["lat"], *c) <= radius(e):
                near.append(el)
        tags = [el.get("tags", {}) for el in near]
        out[e["slug"]] = {"elements": len(near), "building_parts": sum("building:part" in t for t in tags),
                          **{k: sum(k in t for t in tags) for k in TAGS},
                          "towers_masts_spires": sum(t.get("man_made") in ("tower", "mast", "spire") for t in tags),
                          "bridge_ways": sum("bridge" in t and t.get("bridge") != "no" for t in tags)}
    return out


def main():
    entries = [e for e in json.loads(INDEX.read_text())["entries"] if e["lon"] is not None and e["kit"] != "context"]
    w = min(e["lon"] for e in entries) - 0.01
    e_ = max(e["lon"] for e in entries) + 0.01
    s = min(e["lat"] for e in entries) - 0.01
    n = max(e["lat"] for e in entries) + 0.01
    path = fetch_overpass(query_for(entries), [w, s, e_, n], OUT_NAME,
                          "OpenStreetMap building parts, towers and bridge shapes around the v19 landmarks "
                          "(config/landmarks/index.json) via Overpass")
    elements = json.loads((RAW / OUT_NAME).read_text())["elements"]
    summary = summarize(elements, entries)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{len(elements)} elements in {path}")
    for slug, s in summary.items():
        print(f"  {slug:28s} parts {s['building_parts']:4d}  height {s['height']:4d}  roof:shape {s['roof:shape']:4d}"
              f"  roof:colour {s['roof:colour']:3d}  towers {s['towers_masts_spires']:2d}  bridge ways {s['bridge_ways']:3d}")
    print("->", SUMMARY)


if __name__ == "__main__":
    main()
