"""Measure a landmark's shapes on the 2022 LiDAR and the 2024 aerial, for its
dossier (Phase 0 step 4 of docs/landmarks_plan.md).

For every L&I building footprint and every OSM building / building:part
outline within a radius of the landmark's point (config/landmarks/index.json),
this records:
  - heights above ground from the area's LiDAR grid
    (data/processed/<area>_lidar_grid.npz): 50th/90th/99th percentile and
    maximum, over the 0.5 m cells inside the outline, above the median
    classified-ground level in a 3-15 m ring around it
    (pixelphilly.landmark_dossier.height_stats);
  - the roof color in the 2024 City 3-inch aerial (cached zoom-19 tiles,
    data/raw/imagery/CityImagery_2024_3in/19/<y>_<x>.jpg): the median of the
    pixels inside, after dropping the darkest quarter (shadows);
  - for stadiums and the arena, the bowl's shape on the LiDAR
    (pixelphilly.landmark_dossier.bowl_stats): the field's rectangle, level
    and axis, stand heights by compass sector, and rake profiles; for the
    arena, the roof's rectangle, eave, crown and curve (dome_stats);
  - for bridges, a profile along each OSM bridge way: per 10 m bin, the
    median and maximum surface height within 6 m of the centerline (the
    maximum catches a thin arch rib or lift tower the median misses).

Dossier values measured this way cite the dataset (PASDA 7154 for the LiDAR,
the City imagery service for the aerial) and name this script and its output
in a note; rerunning the script reproduces them. Raw files are only read.

Writes output/landmarks/measure/<slug>.json.

Usage: uv run python scripts/50_landmark_measure.py city_hall [more slugs] [--radius 150]
"""

import argparse
import json
from datetime import datetime, timezone

import numpy as np
from PIL import Image
from shapely.geometry import Point, Polygon, shape

from pixelphilly import landmark_dossier as ld
from pixelphilly.bridges import npz_window
from pixelphilly.landmark_dossier import BRIDGE_KITS
from pixelphilly.lidar import RES_M
from pixelphilly.projection import REPO_ROOT, load_config, local_frame
from pixelphilly.sources import RAW

INDEX = REPO_ROOT / "config" / "landmarks" / "index.json"
OUT = REPO_ROOT / "output" / "landmarks" / "measure"
TILES = RAW / "imagery" / "CityImagery_2024_3in" / "19"
Z = 19
SOURCES = {
    "lidar": "https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=7154",
    "aerial": "https://tiles.arcgis.com/tiles/fLeGjb7u4uXqeF9q/arcgis/rest/services/CityImagery_2024_3in/MapServer",
    "footprints": "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/LI_BUILDING_FOOTPRINTS/FeatureServer/0",
    "osm": "https://www.openstreetmap.org/copyright",
}
# Default search radius per structure, meters: big sites need more
RADIUS_M = {"lincoln_financial_field": 220, "citizens_bank_park": 220, "xfinity_mobile_arena": 160,
            "boathouse_row": 380, "art_museum": 160, "tacony_palmyra_bridge": 700}
DEFAULT_RADIUS_M = 120
# The LiDAR area to measure on when it isn't the index's owning region: the
# Tacony-Palmyra is owned by east_riverfront's frame lattice, but that area's
# grid stops at -75.045; lower_northeast's grid covers the whole bridge
LIDAR_AREA = {"tacony_palmyra_bridge": "lower_northeast"}
RING_PAD_M = 20.0
BOWL_KITS = ("stadium_bowl", "arena_dome")
PROFILE_BIN_M = 10.0
PROFILE_HALF_M = 6.0

_tiles = {}


def tile(x, y):
    if (x, y) not in _tiles:
        p = TILES / f"{y}_{x}.jpg"
        _tiles[(x, y)] = np.asarray(Image.open(p).convert("RGB")) if p.exists() else None
    return _tiles[(x, y)]


def aerial_rgb(ring_lonlat):
    """Median lit roof color inside a lon/lat ring, from the cached tiles;
    None when a tile it needs isn't cached."""
    lon, lat = np.array(ring_lonlat).T
    px, py = ld.merc_px(lon, lat, Z)
    x0, x1 = int(px.min() // 256), int(px.max() // 256)
    y0, y1 = int(py.min() // 256), int(py.max() // 256)
    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256, 3), np.uint8)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            t = tile(tx, ty)
            if t is None:
                return None
            mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = t
    c0, r0 = int(px.min()) - x0 * 256, int(py.min()) - y0 * 256
    c1, r1 = int(np.ceil(px.max())) - x0 * 256, int(np.ceil(py.max())) - y0 * 256
    sub = mosaic[r0:r1 + 1, c0:c1 + 1]
    poly = list(zip(px - x0 * 256 - c0, py - y0 * 256 - r0))
    return ld.polygon_rgb(sub, poly)


def outlines(slug, entry, area_cfg, radius):
    """(kind, id, props, lon/lat ring) for L&I footprints and OSM outlines
    within radius of the point; the largest ring of a multipolygon."""
    pt = Point(entry["lon"], entry["lat"])
    deg = radius / 85_000.0  # generous: a degree of longitude is ~85 km here
    near = pt.buffer(deg)
    out = []
    fc = json.loads((RAW / f"{area_cfg['name']}_buildings.geojson").read_text())
    for f in fc["features"]:
        g = shape(f["geometry"])
        if not g.intersects(near):
            continue
        poly = max(g.geoms, key=lambda q: q.area) if g.geom_type == "MultiPolygon" else g
        p = f["properties"]
        out.append(("li", p.get("objectid"), {k: p.get(k) for k in ("bin", "address", "building_name", "approx_hgt",
                                                                       "max_hgt", "base_elevation")},
                    [list(c) for c in poly.exterior.coords]))
    for e in json.loads((RAW / "landmarks_osm.json").read_text())["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or "geometry" not in e or not ("building" in t or "building:part" in t):
            continue
        ring = [[q["lon"], q["lat"]] for q in e["geometry"]]
        if len(ring) < 4 or ring[0] != ring[-1] or not Polygon(ring).intersects(near):
            continue
        keep = {k: v for k, v in t.items() if k.startswith(("building", "roof", "height", "min_height", "name"))}
        out.append(("osm", e["id"], keep, ring))
    return out


def bridge_ways(entry, radius):
    pt = Point(entry["lon"], entry["lat"]).buffer(radius / 85_000.0)
    ways = []
    for e in json.loads((RAW / "landmarks_osm.json").read_text())["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and "geometry" in e and (t.get("bridge") or t.get("man_made") == "bridge") \
                and "Tacony" in t.get("name", "") + t.get("bridge:name", ""):
            line = [(q["lon"], q["lat"]) for q in e["geometry"]]
            if any(pt.contains(Point(p)) for p in line):
                ways.append(e)
    return ways


def profile(grid, a, b):
    """Median and max surface height (NAVD88 m) per bin along a -> b (local m)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = float(np.linalg.norm(b - a))
    u = (b - a) / L
    v = np.array([-u[1], u[0]])
    dsm, (west, north), res = grid["dsm"], grid["origin"], grid["res"]
    H, W = dsm.shape
    rows = []
    for s in np.arange(0.0, L, PROFILE_BIN_M):
        zs = []
        for ds in np.arange(0, PROFILE_BIN_M, res):
            for dt in np.arange(-PROFILE_HALF_M, PROFILE_HALF_M + 1e-9, res):
                x, y = a + u * (s + ds) + v * dt
                c, r = int((x - west) / res), int((north - y) / res)
                if 0 <= r < H and 0 <= c < W and np.isfinite(dsm[r, c]):
                    zs.append(float(dsm[r, c]))
        rows.append({"s_m": round(float(s + PROFILE_BIN_M / 2), 1),
                     "median_m": round(float(np.median(zs)), 2) if zs else None,
                     "max_m": round(float(np.max(zs)), 2) if zs else None, "cells": len(zs)})
    return {"length_m": round(L, 1), "bin_m": PROFILE_BIN_M, "half_width_m": PROFILE_HALF_M, "bins": rows}


def measure(slug, radius=None):
    idx = {e["slug"]: e for e in json.loads(INDEX.read_text())["entries"]}
    entry = idx[slug]
    cfg = load_config(LIDAR_AREA.get(slug, entry["region"]))
    frame = local_frame(cfg)
    radius = radius or RADIUS_M.get(slug, DEFAULT_RADIUS_M)
    grid_path = REPO_ROOT / "data" / "processed" / f"{cfg['name']}_lidar_grid.npz"
    cx, cy = frame.to_local(entry["lon"], entry["lat"])
    pad = radius + 400.0 if entry["kit"] in BRIDGE_KITS else radius + 80.0
    bounds = (cx - pad, cy - pad, cx + pad, cy + pad)
    dsm = npz_window(grid_path, "dsm", bounds, RES_M)
    ground = npz_window(grid_path, "ground", bounds, RES_M)
    if dsm is None:
        raise SystemExit(f"{slug}: no LiDAR in {grid_path}")
    res = {"slug": slug, "area": cfg["name"], "radius_m": radius, "lon": entry["lon"], "lat": entry["lat"],
           "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": SOURCES,
           "method": __doc__.split("Dossier values")[0].strip(), "outlines": []}

    def crop(g, poly_local):
        xs, ys = zip(*poly_local)
        west, north = g["origin"]
        r = g["res"]
        c0 = max(int((min(xs) - RING_PAD_M - west) / r), 0)
        c1 = int((max(xs) + RING_PAD_M - west) / r) + 1
        r0 = max(int((north - max(ys) - RING_PAD_M) / r), 0)
        r1 = int((north - min(ys) + RING_PAD_M) / r) + 1
        return {"dsm": g["dsm"][r0:r1, c0:c1], "origin": (west + c0 * r, north - r0 * r), "res": r}

    for kind, oid, props, ring in outlines(slug, entry, cfg, radius):
        xs, ys = frame.to_local(np.array([p[0] for p in ring]), np.array([p[1] for p in ring]))
        poly_local = list(zip(xs.tolist(), ys.tolist()))
        poly = Polygon(poly_local)
        hs = ld.height_stats(crop(dsm, poly_local), poly_local, ground=crop(ground, poly_local))
        res["outlines"].append({
            "kind": kind, "id": oid, "props": props, "area_m2": round(poly.area, 1),
            "centroid": [round(c, 7) for c in Polygon(ring).centroid.coords[0]],
            "distance_m": round(Point(cx, cy).distance(poly), 1),
            "heights": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in hs.items()},
            "roof": aerial_rgb(ring), "ring": [[round(x, 7), round(y, 7)] for x, y in ring]})
    res["outlines"].sort(key=lambda o: (o["distance_m"], -o["area_m2"]))
    if entry["kit"] in BOWL_KITS:
        # The stadium itself: the largest L&I outline within 40 m of the point
        main = max((o for o in res["outlines"] if o["kind"] == "li" and o["distance_m"] <= 40.0),
                   key=lambda o: o["area_m2"])
        xs, ys = frame.to_local(np.array([p[0] for p in main["ring"]]), np.array([p[1] for p in main["ring"]]))
        poly_local = list(zip(xs.tolist(), ys.tolist()))
        if entry["kit"] == "arena_dome":
            b = ld.dome_stats(crop(dsm, poly_local), poly_local, main["heights"]["ground_m"])
            at = b["roof"]
        else:
            b = ld.bowl_stats(crop(dsm, poly_local), poly_local, main["heights"]["ground_m"])
            at = b["field"]
            # The turf color: the aerial inside the field rectangle shrunk to
            # 80%, clear of the sideline areas and benches
            t = np.radians(at["bearing_deg"])
            u, v = np.array([np.sin(t), np.cos(t)]), np.array([np.cos(t), -np.sin(t)])
            c = np.array(at["center_local"])
            corners = [c + u * su * at["length_m"] * 0.4 + v * sv * at["width_m"] * 0.4
                       for su, sv in ((1, 1), (1, -1), (-1, -1), (-1, 1), (1, 1))]
            lo, la = frame.to_wgs84(np.array([q[0] for q in corners]), np.array([q[1] for q in corners]))
            ring = [[round(float(a), 7), round(float(b_), 7)] for a, b_ in zip(lo, la)]
            at["sample_ring"] = ring
            at["roof"] = aerial_rgb(ring)
        lon, lat = frame.to_wgs84(*at["center_local"])
        at["center_lonlat"] = [round(float(lon), 7), round(float(lat), 7)]
        b["outline"] = f"li:{main['id']}"
        b["ground_m"] = main["heights"]["ground_m"]
        res["bowl"] = b
    if entry["kit"] in BRIDGE_KITS:
        res["profiles"] = []
        for w in bridge_ways(entry, radius):
            # Profile between the way's two farthest-apart nodes: its ends for
            # a line, the long axis for a closed man_made=bridge outline
            g = w["geometry"]
            pts = np.column_stack(frame.to_local(np.array([q["lon"] for q in g]), np.array([q["lat"] for q in g])))
            d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
            i, j = np.unravel_index(int(d2.argmax()), d2.shape)
            a, b = pts[i], pts[j]
            res["profiles"].append({"osm_way": w["id"], "tags": w.get("tags", {}),
                                    "ends": [[g[i]["lon"], g[i]["lat"]], [g[j]["lon"], g[j]["lat"]]],
                                    **profile(dsm, a, b)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.json").write_text(json.dumps(res, indent=1))
    print(f"{slug}: {len(res['outlines'])} outlines" + (f", {len(res.get('profiles', []))} profiles" if "profiles" in res else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--radius", type=float)
    a = ap.parse_args()
    for s in a.slugs:
        measure(s, a.radius)


if __name__ == "__main__":
    main()
