"""Landmark dossiers: the sourced dimensions behind each v19 landmark model.

A dossier (config/landmarks/<slug>.json) records what a hand-built model of
one structure needs: the footprint it replaces, every dimension, the colors
and the kit's parameters. docs/landmarks.md describes the format and the
sources per structure; docs/landmarks_plan.md says why the models exist.

The rule, the same one config/bridge_structures.json follows: every number
sits in a record {"value", "unit", "source": "https://..."} or
{"value", "unit", "estimate": true, "reason"}. No bare numbers in "dims" or
"kit_params", so nothing reaches a model without a citation or a stated
guess. check() enforces it (tests/test_landmark_dossiers.py runs it on every
dossier).

This module also holds the measurement helpers scripts/50_landmark_measure.py
uses: heights above ground from the 2022 LiDAR grid (height_stats) and roof
colors from the 2024 City aerial (polygon_rgb, merc_px). Their results are
cited in dossiers as measurements of those datasets, like the bridges'.
"""

from __future__ import annotations

import math

import numpy as np

# Values a kit can't do without. Kept minimal; Phase 1 (landmarks3d.py) adds
# what each generator turns out to need. Keys are looked up in "dims" first,
# then "kit_params".
KIT_REQUIRED = {
    "mansard_tower": ["height_total_m", "main_block_height_m", "tower_stages"],
    "tower_stages": ["height_total_m", "roof_height_m"],
    "stadium_bowl": ["field", "bowl_rim_height_m"],
    "arena_dome": ["eave_height_m", "roof_top_height_m"],
    "colonnade_portico": ["main_height_m", "column_count"],
    "gabled_row": ["houses"],
    "arch_bascule": ["arch_span_m", "arch_rise_m", "bascule_span_m", "clearance_m"],
}

# Kits for bridges: scripts 04s (wider OSM radius, bridge ways), 49 (wider
# review crop) and 50 (LiDAR profiles) treat these as bridges. bridge_tbd
# marks a bridge whose type the sources haven't settled yet.
BRIDGE_KITS = ("bridge_tbd", "suspension", "arch_bascule")

# Bridges are long; their footprint may lie far from the index point
NEAR_M = 150.0
NEAR_BRIDGE_M = 800.0
MIN_REASON = 10


def _is_url(s) -> bool:
    return isinstance(s, str) and s.startswith("https://")


def _record_errors(path: str, rec: dict) -> list[str]:
    errs = []
    if "unit" not in rec:
        errs.append(f"{path}: no unit")
    if rec.get("estimate"):
        if len(str(rec.get("reason", ""))) <= MIN_REASON:
            errs.append(f"{path}: estimate without a reason")
    elif not _is_url(rec.get("source")):
        errs.append(f"{path}: no https source and not marked an estimate")
    return errs


def _walk(path: str, x) -> list[str]:
    """Errors for every bare number or unsourced record under x."""
    if isinstance(x, dict):
        if "value" in x:
            errs = _record_errors(path, x)
            v = x["value"]
            if isinstance(v, (list, dict)):  # e.g. a profile: the record covers it
                return errs
            if not isinstance(v, (int, float, str, bool)):
                errs.append(f"{path}: value of unexpected type")
            return errs
        return [e for k, v in x.items() for e in _walk(f"{path}.{k}", v)]
    if isinstance(x, list):
        return [e for i, v in enumerate(x) for e in _walk(f"{path}[{i}]", v)]
    if isinstance(x, bool) or isinstance(x, str) or x is None:
        return []
    if isinstance(x, (int, float)):
        return [f"{path}: bare number {x} (needs a source or an estimate record)"]
    return [f"{path}: unexpected {type(x).__name__}"]


def _rings(fp: dict):
    if "polygon" in fp:
        return [fp["polygon"]]
    return list(fp.get("polygons") or [])


def _meters_between(lon0, lat0, lon1, lat1) -> float:
    k = math.cos(math.radians((lat0 + lat1) / 2))
    return math.hypot((lon1 - lon0) * 111_320.0 * k, (lat1 - lat0) * 110_574.0)


def _ref_errors(path: str, x, dims: dict) -> list[str]:
    """kit_params may name a dims key instead of repeating a record (e.g.
    "z1_m": "tower_masonry_top_m"). A string under a key ending in _m must
    be such a name."""
    if isinstance(x, dict):
        if "value" in x:
            return []
        errs = []
        for k, v in x.items():
            if isinstance(v, str) and k.endswith("_m") and v not in dims:
                errs.append(f"{path}.{k}: '{v}' is not a dims key")
            errs += _ref_errors(f"{path}.{k}", v, dims)
        return errs
    if isinstance(x, list):
        return [e for i, v in enumerate(x) for e in _ref_errors(f"{path}[{i}]", v, dims)]
    return []


def _footprint_errors(fp: dict, entry: dict, bridge: bool) -> list[str]:
    from shapely.geometry import Point, Polygon

    errs = []
    if not _is_url(fp.get("source")):
        errs.append("footprint: no https source")
    if not isinstance(fp.get("replaces"), dict):
        errs.append("footprint: no 'replaces' record")
    rings = _rings(fp)
    if not rings:
        return errs + ["footprint: no polygon"]
    near = NEAR_BRIDGE_M if bridge else NEAR_M
    best = math.inf
    for i, ring in enumerate(rings):
        if len(ring) < 4 or list(ring[0]) != list(ring[-1]):
            errs.append(f"footprint[{i}]: ring not closed")
            continue
        poly = Polygon(ring)
        if not poly.is_valid or poly.area <= 0:
            errs.append(f"footprint[{i}]: invalid polygon")
            continue
        if poly.contains(Point(entry["lon"], entry["lat"])):
            best = 0.0
        else:
            q = poly.exterior.interpolate(poly.exterior.project(Point(entry["lon"], entry["lat"])))
            best = min(best, _meters_between(entry["lon"], entry["lat"], q.x, q.y))
    if best > near:
        errs.append(f"footprint: {best:.0f} m from the landmark point (limit {near:.0f} m)")
    return errs


def _color_errors(name: str, c) -> list[str]:
    errs = []
    rgb = c.get("rgb") if isinstance(c, dict) else None
    if not (isinstance(rgb, list) and len(rgb) == 3 and all(isinstance(v, int) and 0 <= v <= 255 for v in rgb)):
        errs.append(f"colors.{name}: rgb must be three ints 0-255")
    if isinstance(c, dict):
        if c.get("estimate"):
            if len(str(c.get("reason", ""))) <= MIN_REASON:
                errs.append(f"colors.{name}: estimate without a reason")
        elif not _is_url(c.get("source")):
            errs.append(f"colors.{name}: no https source and not marked an estimate")
    return errs


def check(d: dict, entry: dict) -> list[str]:
    """Errors in dossier d for index entry entry ([] when it passes)."""
    errs = []
    for k in ("slug", "name", "kit", "about", "footprint", "dims", "colors", "kit_params", "credits"):
        if k not in d:
            errs.append(f"missing '{k}'")
    if errs:
        return errs
    if d["slug"] != entry["slug"]:
        errs.append(f"slug {d['slug']} != index {entry['slug']}")
    if d["kit"] != entry["kit"]:
        errs.append(f"kit {d['kit']} != index {entry['kit']}")
    errs += _walk("dims", d["dims"])
    errs += _walk("kit_params", d["kit_params"])
    errs += _ref_errors("kit_params", d["kit_params"], d["dims"])
    for name, c in d["colors"].items():
        errs += _color_errors(name, c)
    bridge = d["kit"] in BRIDGE_KITS
    errs += _footprint_errors(d["footprint"], entry, bridge)
    for key in KIT_REQUIRED.get(d["kit"], []):
        if key not in d["dims"] and key not in d["kit_params"]:
            errs.append(f"kit {d['kit']} needs {key}")
    if not (isinstance(d["credits"], list) and d["credits"]):
        errs.append("credits: empty")
    return errs


# --- Measurement helpers (scripts/50_landmark_measure.py) ---

def _mask(shape, poly_px):
    """Boolean mask of the pixels whose centers fall inside poly_px
    ((col, row) pairs in pixel units)."""
    # Even-odd crossing test, vectorized over the pixel centers (no
    # matplotlib in the environment)
    H, W = shape
    x, y = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    p = np.asarray(poly_px, float)
    if (p[0] != p[-1]).any():
        p = np.vstack([p, p[:1]])
    inside = np.zeros((H, W), bool)
    for (x0, y0), (x1, y1) in zip(p[:-1], p[1:]):
        if y0 == y1:
            continue
        crosses = (y0 > y) != (y1 > y)
        xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (x < xi)
    return inside


def _to_px(grid, poly_local):
    west, north = grid["origin"]
    res = grid["res"]
    return [((x - west) / res, (north - y) / res) for x, y in poly_local]


def height_stats(grid, poly_local, ring_m=(3.0, 15.0), ground=None) -> dict:
    """Heights above ground inside a polygon (local meters) on a LiDAR grid
    window ({"dsm", "origin", "res"}, from bridges.npz_window).

    Ground: the median of the grid's ground array (classified ground returns)
    inside a ring ring_m outside the polygon when `ground` is given, else the
    10th percentile of the surface in that ring (streets and sidewalks are the
    low cells beside a building; the median would catch neighbors' roofs).
    Returns the ground level and the 50th, 90th, 99th percentile and maximum
    surface height above it, in meters, over the cells with returns."""
    from shapely.geometry import Polygon

    dsm = grid["dsm"]
    poly = Polygon(poly_local)
    inside = _mask(dsm.shape, _to_px(grid, poly_local))
    outer = poly.buffer(ring_m[1])
    inner = poly.buffer(ring_m[0])
    ring = _mask(dsm.shape, _to_px(grid, list(outer.exterior.coords))) & \
        ~_mask(dsm.shape, _to_px(grid, list(inner.exterior.coords)))
    if ground is not None:
        g = ground["dsm"][ring]
        g = g[np.isfinite(g)]
        g0 = float(np.median(g)) if g.size else None
    else:
        g = dsm[ring]
        g = g[np.isfinite(g)]
        g0 = float(np.percentile(g, 10)) if g.size else None
    z = dsm[inside]
    z = z[np.isfinite(z)]
    out = {"cells": int(z.size), "ground_m": g0, "p50_m": None, "p90_m": None, "p99_m": None, "max_m": None,
           "res_m": grid["res"]}
    if z.size and g0 is not None:
        h = z - g0
        out.update(p50_m=float(np.percentile(h, 50)), p90_m=float(np.percentile(h, 90)),
                   p99_m=float(np.percentile(h, 99)), max_m=float(h.max()))
    return out


def polygon_rgb(img: np.ndarray, poly_px, drop_dark: float = 0.25) -> dict:
    """Median color of an image's pixels inside poly_px ((col, row) pairs),
    after dropping the darkest drop_dark share by luminance (shadows cast on
    the roof by parapets, towers and neighbors)."""
    m = _mask(img.shape[:2], poly_px)
    px = img[m].astype(float)
    if not len(px):
        return {"rgb": None, "pixels": 0}
    lum = px @ np.array([0.299, 0.587, 0.114])
    keep = px[lum >= np.quantile(lum, drop_dark)] if drop_dark > 0 else px
    return {"rgb": [int(round(v)) for v in np.median(keep, axis=0)], "pixels": int(len(keep))}


TILE = 256


def merc_px(lon, lat, z: int):
    """Global Web Mercator pixel coordinates at zoom z (tile x = px // 256)."""
    n = TILE * 2**z
    lon = np.asarray(lon, float)
    lat = np.radians(np.asarray(lat, float))
    return (lon + 180.0) / 360.0 * n, (1.0 - np.log(np.tan(lat) + 1.0 / np.cos(lat)) / math.pi) / 2.0 * n


def merc_lonlat(px, py, z: int):
    n = TILE * 2**z
    lon = np.asarray(px, float) / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1.0 - 2.0 * np.asarray(py, float) / n))))
    return lon, lat


def photo_rgb(path, box, drop_dark: float = 0.25) -> list[int]:
    """Median color of a box (x0, y0, x1, y1, pixels) in a reference photo
    (data/landmarks/refs/<slug>/...), darkest drop_dark share dropped:
    the colors a dossier reads from a photo, recomputable by the tests."""
    from PIL import Image

    img = np.asarray(Image.open(path).convert("RGB"))
    x0, y0, x1, y1 = box
    return polygon_rgb(img, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], drop_dark)["rgb"]


def aerial_rgb_of(measure: dict, outline: str):
    """The roof color scripts/50_landmark_measure.py recorded for an outline
    ("li:<objectid>" or "osm:<way id>") in a slug's measure output."""
    if outline == "bowl:field":  # the turf sample in the bowl analysis
        return ((measure.get("bowl") or {}).get("field", {}).get("roof") or {}).get("rgb")
    kind, oid = outline.split(":")
    for o in measure["outlines"]:
        if o["kind"] == kind and str(o["id"]) == oid:
            return (o.get("roof") or {}).get("rgb")
    return None


def bowl_stats(grid, poly_local, ground_m: float, field_max_m: float = 2.0, n_sectors: int = 12,
               bin_m: float = 2.0, half_m: float = 3.0, reach_m: float = 200.0) -> dict:
    """The shape of a stadium bowl on a LiDAR grid window, for stadium_bowl
    and arena_dome dossiers.

    field: the playing surface, found as the low, flat region at the bowl's
    center (cells inside the outline within field_max_m of the outline's
    5th-percentile height, flood-filled from the low cell nearest the
    outline's centroid), with its minimum rotated rectangle: length and
    width, the compass bearing of the long axis (0-180, clockwise from
    north), its center (local m) and its level relative to ground_m (the
    street around the stadium; a sunken field is negative).
    sectors: n_sectors compass sectors around the field center, each with
    the 50th and 95th percentile height above ground of the stands inside
    the outline (canopies show as high sectors, open end zones as low ones).
    profiles: the maximum height per bin_m along the field's four half-axes,
    within half_m of each, out to reach_m (the seating rake)."""
    from shapely.geometry import MultiPoint, Point, Polygon

    dsm = grid["dsm"].astype(float)
    west, north = grid["origin"]
    res = grid["res"]
    H, W = dsm.shape
    inside = _mask(dsm.shape, _to_px(grid, poly_local)) & np.isfinite(dsm)
    h = dsm - ground_m
    floor = float(np.percentile(h[inside], 5))
    low = inside & (h <= floor + field_max_m)
    rows, cols = np.nonzero(low)
    cx, cy = Polygon(poly_local).centroid.coords[0]
    ex = west + (cols + 0.5) * res
    ny = north - (rows + 0.5) * res
    k = int(np.argmin((ex - cx) ** 2 + (ny - cy) ** 2))
    comp = np.zeros_like(low)
    comp[rows[k], cols[k]] = True
    while True:  # 4-connected flood fill within the low cells
        grow = comp.copy()
        grow[1:] |= comp[:-1]
        grow[:-1] |= comp[1:]
        grow[:, 1:] |= comp[:, :-1]
        grow[:, :-1] |= comp[:, 1:]
        grow &= low
        if grow.sum() == comp.sum():
            break
        comp = grow
    fr, fc = np.nonzero(comp)
    pts = np.column_stack([west + (fc + 0.5) * res, north - (fr + 0.5) * res])
    rect = MultiPoint(pts).minimum_rotated_rectangle
    c = np.array(rect.exterior.coords[:4])
    e1, e2 = c[1] - c[0], c[2] - c[1]
    # The hull runs through cell centers; add a cell to each side
    l1, l2 = np.linalg.norm(e1) + res, np.linalg.norm(e2) + res
    along = e1 if l1 >= l2 else e2
    u = along / np.linalg.norm(along)
    bearing = float(np.degrees(np.arctan2(u[0], u[1])) % 180.0)
    center = np.array(rect.centroid.coords[0])
    field = {"length_m": float(max(l1, l2)), "width_m": float(min(l1, l2)), "bearing_deg": bearing,
             "center_local": [float(center[0]), float(center[1])], "level_m": float(np.median(h[comp])),
             "cells": int(comp.sum())}

    yy, xx = np.nonzero(inside & ~comp)
    sx, sy = west + (xx + 0.5) * res - center[0], north - (yy + 0.5) * res - center[1]
    ang = np.degrees(np.arctan2(sx, sy)) % 360.0
    hs = h[yy, xx]
    step = 360.0 / n_sectors
    sectors = []
    for i in range(n_sectors):
        a0 = (i * step - step / 2) % 360.0
        sel = ((ang - a0) % 360.0) < step
        z = hs[sel]
        sectors.append({"bearing_deg": i * step, "cells": int(z.size),
                        "p50_m": float(np.percentile(z, 50)) if z.size else None,
                        "p95_m": float(np.percentile(z, 95)) if z.size else None})

    v = np.array([-u[1], u[0]])
    profiles = {}
    allx = west + (np.arange(W) + 0.5) * res
    ally = north - (np.arange(H) + 0.5) * res
    X, Y = np.meshgrid(allx - center[0], ally - center[1])
    for name, d in (("long_pos", u), ("long_neg", -u), ("short_pos", v), ("short_neg", -v)):
        s = X * d[0] + Y * d[1]
        t = X * -d[1] + Y * d[0]
        sel = inside & (s >= 0) & (s < reach_m) & (np.abs(t) <= half_m)
        bins = (s[sel] // bin_m).astype(int)
        z = h[sel]
        prof = []
        for b in range(int(reach_m // bin_m)):
            zb = z[bins == b]
            prof.append(round(float(zb.max()), 2) if zb.size else None)
        profiles[name] = {"bin_m": bin_m, "max_m": prof}
    return {"field": field, "sectors": sectors, "profiles": profiles, "floor_p5_m": floor}


def dome_stats(grid, poly_local, ground_m: float, roof_share: float = 0.7, bin_m: float = 2.0) -> dict:
    """An arena roof on a LiDAR grid window (arena_dome dossiers).

    The roof is the connected region of cells inside the outline higher than
    roof_share of the outline's 99th-percentile height (lower annexes and
    concourses drop out), flood-filled from the highest cell. Returns its
    minimum rotated rectangle (length, width, compass bearing of the long
    axis, center), the crown (99th percentile) and the eave (the 2nd
    percentile of the roof cells on the rectangle's outer edge band, 3 m
    wide), all in meters above ground_m, plus the maximum height per bin_m
    along both axes through the center (the roof's curve)."""
    from shapely.geometry import MultiPoint

    dsm = grid["dsm"].astype(float)
    west, north = grid["origin"]
    res = grid["res"]
    H, W = dsm.shape
    inside = _mask(dsm.shape, _to_px(grid, poly_local)) & np.isfinite(dsm)
    h = dsm - ground_m
    top = float(np.percentile(h[inside], 99))
    high = inside & (h >= roof_share * top)
    r0, c0 = np.unravel_index(int(np.argmax(np.where(high, h, -np.inf))), h.shape)
    comp = np.zeros_like(high)
    comp[r0, c0] = True
    while True:
        grow = comp.copy()
        grow[1:] |= comp[:-1]
        grow[:-1] |= comp[1:]
        grow[:, 1:] |= comp[:, :-1]
        grow[:, :-1] |= comp[:, 1:]
        grow &= high
        if grow.sum() == comp.sum():
            break
        comp = grow
    rr, cc = np.nonzero(comp)
    ex, ny = west + (cc + 0.5) * res, north - (rr + 0.5) * res
    rect = MultiPoint(np.column_stack([ex, ny])).minimum_rotated_rectangle
    c = np.array(rect.exterior.coords[:4])
    e1, e2 = c[1] - c[0], c[2] - c[1]
    l1, l2 = np.linalg.norm(e1) + res, np.linalg.norm(e2) + res
    along = e1 if l1 >= l2 else e2
    u = along / np.linalg.norm(along)
    v = np.array([-u[1], u[0]])
    center = np.array(rect.centroid.coords[0])
    L, Wd = max(l1, l2), min(l1, l2)
    s = (ex - center[0]) * u[0] + (ny - center[1]) * u[1]
    t = (ex - center[0]) * v[0] + (ny - center[1]) * v[1]
    z = h[rr, cc]
    edge = (np.abs(s) >= L / 2 - 3.0) | (np.abs(t) >= Wd / 2 - 3.0)
    profiles = {}
    for name, (a, b, span) in {"long": (s, t, L), "short": (t, s, Wd)}.items():
        sel = np.abs(b) <= 3.0
        bins = np.floor((a[sel] + span / 2) / bin_m).astype(int)
        prof = []
        for k in range(int(np.ceil(span / bin_m))):
            zb = z[sel][bins == k]
            prof.append(round(float(zb.max()), 2) if zb.size else None)
        profiles[name] = {"bin_m": bin_m, "from_m": -span / 2, "max_m": prof}
    return {"roof": {"length_m": float(L), "width_m": float(Wd),
                     "bearing_deg": float(np.degrees(np.arctan2(u[0], u[1])) % 180.0),
                     "center_local": [float(center[0]), float(center[1])], "cells": int(comp.sum())},
            "crown_m": float(np.percentile(z, 99)), "eave_m": float(np.percentile(z[edge], 2)),
            "profiles": profiles}
