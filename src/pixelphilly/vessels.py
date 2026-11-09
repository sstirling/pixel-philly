"""Ships and piers (Nov. 5, Stephen: "fix ships").

Three problems, one module:
- The water repaint (pixelphilly.waterpaint) repainted ship decks, hulls and
  a brick pier as river: inside the NHD polygon its color test
  (|rgb - [108,101,64]| < 68 for South Philly) accepts dark hulls, shadows
  and brick, and only scene-geometry silhouettes were protected. Reviewed
  vessel outlines (config/vessels.json, traced from the 2024 aerial) and OSM
  piers now form a protection mask the repaint never touches.
- Most 2024 vessels had no 3D geometry (not in the 2022 LiDAR), and ships
  that were there came out in fragments (the structure rules' solidity,
  roughness and 60 m² gates) standing on the pier's ground level. A reviewed
  hull becomes one vessel: LiDAR heights inside it where the same hull was
  there in 2022, gaps filled, base at the water level; otherwise a flat hull
  at a recorded estimate (vessel_parts).
- Tracing: trace() finds hull candidates in an aerial window (not river
  colored, not a shadow, not a pier); a person reviews and assigns them.

Heights in config/vessels.json are labelled by source: "lidar" (deck height
measured in the 2022 LiDAR for the same hull), "shadow" (shadow length vs. a
building of known height nearby; an estimate) or "default" (by vessel type;
an assumption).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[2]
VESSELS = REPO_ROOT / "config" / "vessels.json"

# Tracing (trace): a hull pixel differs from the river's median color by
# more than TRACE_DIST (max channel) after a 5 px median filter, and isn't a
# shadow (darker than SHADOW_V x the river's brightness with the river's
# hue family). Measured on the Navy Yard and Pier 82 (2024 z19 tiles,
# ~0.23 m/px): gray decks 140-170, hull sides 45-70, shadows ~(45,42,28),
# river (108,101,64) +- 10.
TRACE_DIST = 38
DECK_V = 1.15  # deck pixels are this much brighter than the river
HULL_EDGE_PX = 3  # grow decks ~0.5 m back over the hull edge
TRACE_OPEN_PX = 5  # ripples and glints
TRACE_CLOSE_PX = 5  # ~1 m: deck gaps; wider closing merged nested hulls across the dark gap between them
PIER_LINE_WIDTH_M = 3.0  # an OSM pier drawn as a line, without a width tag

# Hull heights (vessel_parts): LiDAR cells at least this far above the water
# count as the hull; a hull is "measured" when this share of its cells has one
VESSEL_MIN_ABOVE_WATER_M = 2.0
VESSEL_MEASURED_SHARE = 0.3


def _filter(mask: np.ndarray, flt) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(flt)) > 127


def _open(m, px):
    return _filter(_filter(m, ImageFilter.MinFilter(px)), ImageFilter.MaxFilter(px))


def _close(m, px):
    return _filter(_filter(m, ImageFilter.MaxFilter(px)), ImageFilter.MinFilter(px))


def _components(mask: np.ndarray):
    """[(polygon in px, area px)] of 8-connected regions, holes filled."""
    from rasterio.features import shapes
    from shapely.geometry import Polygon, shape

    out = []
    for g, _ in shapes(mask.astype(np.uint8), mask=mask, connectivity=8):
        p = shape(g)
        out.append(Polygon(p.exterior))
    return out


def trace(rgb: np.ndarray, water: np.ndarray, pier: np.ndarray, mpp: float, min_m2: float = 150.0,
          deck_v: float = None) -> list:
    """Hull candidates in an aerial window: boolean masks (holes filled) of
    regions inside `water`, outside `pier`, whose color isn't the river's and
    isn't a shadow on it, at least min_m2. mpp: meters per pixel."""
    from rasterio.features import rasterize

    rgb = np.asarray(rgb)
    sm = np.asarray(Image.fromarray(rgb).filter(ImageFilter.MedianFilter(5))).astype(int)
    ref = water & ~pier
    if ref.sum() < 100:
        return []
    med = np.median(sm[ref], axis=0)
    dist = np.abs(sm - med).max(axis=2)
    v = sm.max(axis=2) / 255.0
    med_v = med.max() / 255.0
    # Decks and superstructures only: brighter than the river. Shadows on the
    # water and dark hull sides are both dark and both pick up blue skylight,
    # so color can't tell them apart; a dark side is ~1 m wide in the aerial
    # and comes back with HULL_EDGE_PX. Nested hulls stay apart along the dark
    # line between their decks.
    obj = water & ~pier & (dist > TRACE_DIST) & (v > (DECK_V if deck_v is None else deck_v) * med_v)
    obj = _open(obj, TRACE_OPEN_PX)
    obj = _close(obj, TRACE_CLOSE_PX)
    obj = _filter(obj, ImageFilter.MaxFilter(HULL_EDGE_PX)) & water & ~pier
    min_px = min_m2 / (mpp * mpp)
    out = []
    for poly in _components(obj):
        if poly.area < min_px:
            continue
        m = rasterize([(poly, 1)], out_shape=obj.shape, fill=0, dtype="uint8").astype(bool)
        out.append(m)
    return out


def pier_polygons(elements) -> list:
    """Shapely WGS84 polygons of OSM man_made=pier: closed ways as areas,
    open ways buffered to their width tag (or PIER_LINE_WIDTH_M), relations
    by their outer members. Ships (building=ship) aren't piers."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    out = []
    for e in elements:
        t = e.get("tags", {})
        if t.get("man_made") != "pier":
            continue
        rings = []
        if e["type"] == "way" and e.get("geometry"):
            rings = [[(p["lon"], p["lat"]) for p in e["geometry"]]]
        elif e["type"] == "relation":
            rings = [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in e.get("members", [])
                     if m.get("role") == "outer" and m.get("geometry")]
        for c in rings:
            if len(c) >= 4 and c[0] == c[-1]:
                g = Polygon(c).buffer(0)
            elif len(c) >= 2:
                try:
                    w = float(str(t.get("width", "")).split()[0])
                except (ValueError, IndexError):
                    w = PIER_LINE_WIDTH_M
                lat = c[0][1]
                deg = (w / 2) / (111_320 * math.cos(math.radians(lat)))
                g = LineString(c).buffer(deg, cap_style=2)
            else:
                continue
            if not g.is_empty:
                out.append(g)
    return out


def load(path: Path = VESSELS, statuses=("accepted", "protect")) -> list:
    """Reviewed vessels: [{"id", "group", "polygon" (WGS84 shapely), "status",
    "kind", "h", "h_source", "base", "flat", ...}] from config/vessels.json.
    "accepted" are hulls (3D unless "flat"); "protect" are traces a reviewer
    left as vessel-like but unclassified (protected from the repaint only);
    "rejected" traces (quay edges, dock walls, cranes) are never returned."""
    from shapely.geometry import shape

    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text())
    return [{**v, "polygon": shape(v["geometry"])} for v in data.get("vessels", []) if v.get("status") in statuses]


def hulls(path: Path = VESSELS) -> list:
    """Accepted vessels that get 3D hulls (not "flat": under way)."""
    return [v for v in load(path, ("accepted",)) if not v.get("flat")]


def protect_geometry(cfg, frame, cam, x_origin: float, y_origin: float, vessel_list=None, piers=None):
    """Mosaic-pixel geometry the water repaint never touches: reviewed vessel
    outlines (accepted and protect) and OSM piers, swept from the water up to
    PROTECT_SWEEP_M and grown PROTECT_GROW_PX."""
    from shapely.affinity import translate
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from .projection import swept_screen_polygon
    from .sources import RAW

    if vessel_list is None:
        vessel_list = load()
    if piers is None:
        path = RAW / f"{cfg['name']}_piers.json"
        piers = pier_polygons(json.loads(path.read_text())["elements"]) if path.exists() else []
    # Swept only to a low deck: a raised hull or superstructure is scene
    # geometry and already in the building masks the repaint respects;
    # sweeping higher would keep river behind a low hull from repainting
    geoms = [swept_screen_polygon(cam, frame, g, PROTECT_SWEEP_M)
             for g in [v["polygon"] for v in vessel_list] + list(piers)]
    if not geoms:
        return Polygon()
    return translate(unary_union(geoms).buffer(PROTECT_GROW_PX), -x_origin, -y_origin)


PROTECT_SWEEP_M = 4.0  # a pier deck, a barge's or a hull's flat aerial texture
PROTECT_GROW_PX = 3  # drawn outlines run a pixel or two past the geometry


def vessel_parts(hull, struct: np.ndarray, origin, res: float, water_level: float, default_h: float):
    """(parts [{"h", "polys"}], measured) for one reviewed hull (shapely,
    local m); measured is True when the LiDAR shaped it.

    Where the 2022 LiDAR saw this hull (VESSEL_MEASURED_SHARE of its cells at
    least VESSEL_MIN_ABOVE_WATER_M above the water), the class-1 grid shapes
    it with lidar.building_parts at base = water_level, after filling gaps
    (no returns, or returns at water level) from neighboring cells, so the
    hull stays whole. Otherwise one flat part of default_h."""
    from rasterio.features import rasterize

    from . import lidar

    minx, miny, maxx, maxy = hull.bounds
    c0 = max(int((minx - origin[0]) / res) - 1, 0)
    c1 = min(int((maxx - origin[0]) / res) + 2, struct.shape[1])
    r0 = max(int((origin[1] - maxy) / res) - 1, 0)
    r1 = min(int((origin[1] - miny) / res) + 2, struct.shape[0])
    flat = [{"h": float(default_h), "polys": [[list(hull.exterior.coords), *[list(i.coords) for i in hull.interiors]]]}]
    if c1 <= c0 or r1 <= r0:
        return flat, False
    win_origin = (origin[0] + c0 * res, origin[1] - r0 * res)
    tf = lidar._transform(win_origin, res)
    h = struct[r0:r1, c0:c1].astype(np.float32).copy()
    inside = rasterize([(hull, 1)], out_shape=h.shape, transform=tf, fill=0, dtype="uint8").astype(bool)
    if not inside.any():
        return flat, False
    with np.errstate(invalid="ignore"):
        hull_cells = inside & (h - water_level >= VESSEL_MIN_ABOVE_WATER_M)
    if hull_cells.sum() < VESSEL_MEASURED_SHARE * inside.sum():
        return flat, False
    h[~hull_cells] = np.nan
    for _ in range(400):  # grow the deck into gaps, as building_parts refills noise
        gap = inside & np.isnan(h)
        if not gap.any():
            break
        h[gap] = lidar._median3(np.where(inside, h, np.nan))[gap]
    if np.isnan(h[inside]).any():  # a gap the median couldn't reach: the deck's low quartile
        h[inside & np.isnan(h)] = np.nanpercentile(h[hull_cells], 25)
    grid = np.full(struct.shape, np.nan, np.float32)
    grid[r0:r1, c0:c1] = np.where(inside, h, np.nan)
    parts = lidar.building_parts(hull, grid, origin, res, base=water_level)
    return (parts, True) if parts else (flat, False)


FRAGMENT_SHARE = 0.5  # a LiDAR structure region this much inside a reviewed hull is that hull's fragment


def drop_fragments(s_parts, hull_polys):
    """(kept parts, regions dropped): LiDAR structure regions
    (lidar.structures parts, grouped by "region") lying FRAGMENT_SHARE or
    more inside a reviewed hull (local m) give way to the whole hull; cranes
    and quay objects that only touch a hull stay."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if not hull_polys:
        return list(s_parts), 0
    hulls = unary_union(hull_polys)
    by_region = {}
    for p in s_parts:
        by_region.setdefault(p["region"], []).append(p)
    kept, dropped = [], 0
    for k, parts in by_region.items():
        g = unary_union([Polygon(r[0], r[1:]) for p in parts for r in p["polys"]])
        if g.area > 0 and g.intersection(hulls).area / g.area >= FRAGMENT_SHARE:
            dropped += 1
        else:
            kept.extend(parts)
    return kept, dropped
