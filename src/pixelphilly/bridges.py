"""Bridges over water (Nov. 5, Stephen: "several of the bridges don't look
correct... water is bleeding onto the roads").

Cause: a bridge deck is flat aerial texture in the render, and its asphalt
and shadows often fall inside the river color test (South Philly: within 68
levels of [108,101,64]); the drawing also puts the deck and its truss a few
pixels off the render's deck. The water repaint then painted deck, truss and
railing pixels blue (the Ben Franklin's truss, the Platt and Walt Whitman
decks).

Fix: a band around each road or rail line where it crosses mapped water
(City Street_Centerline and rail lines, the expressways at their wider
buffer; NHD and PWD water), swept a few meters below and above the water on
screen. Inside the band the repaint takes only pixels the RAW drawing drew
as water: close to the colors the drawing used for the river just outside
the band (refine). Everything else in the band keeps its drawn pixels. The
real river under and beside a bridge still repaints, because the model
draws it as water; a deck stays a deck. Outside the bands nothing changes.

Nov. 8: where all the river in a frame's view lies inside bands, there is
no ring to learn the drawn colors from; those frames are repainted last
with colors from the nearest frames (SampleBank).
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageFilter

# Half widths (m) of the band around a centerline over water, by City street
# class (1 expressway ... 5 local; 9-15 ramps and others) and for rail
CLASS_HALF_WIDTH_M = {1: 18.0, 2: 12.0, 3: 10.0, 4: 8.0, 5: 7.0}
RAMP_HALF_WIDTH_M = 9.0
RAIL_HALF_WIDTH_M = 6.0
DEFAULT_HALF_WIDTH_M = 8.0
MIN_OVER_WATER_M = 8.0  # shorter crossings are shoreline noise
MARGIN_M = 6.0  # past the water edge, so the abutment's join is in the band
# Screen sweep of the band (m): the drawn deck and truss sit a little below
# and above the render's flat deck
SWEEP_LOW_M = -25.0
SWEEP_HIGH_M = 12.0

# refine(): drawn-water palette from the ring of water just outside the band
RING_PX = 48
PALETTE_COLORS = 8
PALETTE_MIN_SHARE = 0.05
COLOR_TOL = 30
CLOSE_PX = 9  # ripple dashes and antialiased specks inside the drawn river


def deck_geometry(lines, water, min_len_m: float = MIN_OVER_WATER_M, margin_m: float = MARGIN_M):
    """Union of bands (local m) for [(line, half width m)] where a line runs
    over `water` (local m) for at least min_len_m: the over-water stretch,
    extended margin_m past the water's edge, buffered by its half width."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if water is None or water.is_empty:
        return Polygon()
    grown = water.buffer(margin_m)
    out = []
    for line, half in lines:
        if line.is_empty or not line.intersects(water):
            continue
        if line.intersection(water).length < min_len_m:
            continue
        out.append(line.intersection(grown).buffer(half, cap_style=2))
    return unary_union(out) if out else Polygon()


def _filter(m, flt):
    return np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(flt)) > 127


def ring_sample(water: np.ndarray, drawing: np.ndarray, band: np.ndarray) -> np.ndarray | None:
    """(N, 3) uint8 sample of the river's drawn colors: water-mask pixels of
    the view at least RING_PX away from any band (a ring right next to a band
    can hold the drawn deck, which the drawing shifts off the render's deck;
    deck colors stay rare farther out). None when there are fewer than 200
    such pixels: every bit of river in view lies in a band."""
    ring = water & ~_filter(band, ImageFilter.MaxFilter(2 * RING_PX + 1))
    if ring.sum() < 200:
        return None
    return drawing[ring][::7]


def _palette(sample: np.ndarray) -> np.ndarray:
    """The sample's main colors: PALETTE_COLORS quantized, keeping those with
    at least PALETTE_MIN_SHARE of the pixels."""
    q = Image.fromarray(sample.reshape(-1, 1, 3).astype(np.uint8)).quantize(colors=PALETTE_COLORS)
    idx = np.asarray(q).ravel()
    n = int(idx.max()) + 1  # quantize can return fewer colors than asked
    pal = np.asarray(q.getpalette()[:n * 3], int).reshape(-1, 3)
    counts = np.bincount(idx, minlength=n)[:n]
    return pal[counts >= PALETTE_MIN_SHARE * counts.sum()]


def refine(water: np.ndarray, drawing: np.ndarray, band: np.ndarray, deck: np.ndarray | None = None,
           sample: np.ndarray | None = None) -> np.ndarray:
    """The repaint's water mask with bridge bands made drawing-aware: inside
    `band`, a pixel stays water only if the raw drawing drew it as water
    (within COLOR_TOL of a color the drawing used for the river in the ring
    just outside the band), after closing over ripple dashes.

    sample: drawn-river pixels from nearby frames (SampleBank.near), used
    when this view has no ring of its own. Without either, the band keeps
    the drawing."""
    if not band.any() or not water.any():
        return water
    if sample is None:
        sample = ring_sample(water, drawing, band)
    if sample is None or len(sample) == 0:
        out = water & ~band  # no drawn river to compare with: keep the drawing
        return out & ~deck if deck is not None else out
    pal = _palette(sample)
    d = drawing.astype(int)
    near = np.zeros(band.shape, bool)
    for c in pal:
        near |= np.abs(d - c).max(axis=2) < COLOR_TOL
    drawn = near | ~band  # outside the band, the drawing check doesn't apply
    drawn = _filter(_filter(drawn, ImageFilter.MaxFilter(CLOSE_PX)), ImageFilter.MinFilter(CLOSE_PX))
    out = water.copy()
    out[band] = water[band] & drawn[band]
    if deck is not None:
        # The deck itself, where the render has it: never water (dark asphalt
        # and its shadow can be the drawn river's colors)
        out &= ~deck
    return out


class SampleBank:
    """Drawn-river samples by frame cell, for views whose river lies wholly
    inside bridge bands (Nov. 8 review: the Schuylkill at Walnut St came out
    as a block of raw teal with straight frame edges; an estimated 12 frames
    across 6 areas had no ring). Colors come from the nearest frames, not
    the whole area, because one area can draw two rivers differently (the
    brown Delaware and the teal Schuylkill in south_lidar)."""

    CAP = 4000  # px kept per cell

    def __init__(self):
        self.cells = {}

    def add(self, cell, sample: np.ndarray | None) -> None:
        if sample is None or len(sample) == 0:
            return
        step = max(1, -(-len(sample) // self.CAP))  # every k-th pixel: deterministic
        self.cells[tuple(cell)] = np.asarray(sample, np.uint8).reshape(-1, 3)[::step]

    def near(self, cell, max_radius: int = 4) -> np.ndarray | None:
        """Samples of the stored cells at the smallest Chebyshev radius
        (1..max_radius) that has any, concatenated; None if none."""
        c0, r0 = cell
        for r in range(1, max_radius + 1):
            got = [s for (c, w), s in sorted(self.cells.items())
                   if max(abs(c - c0), abs(w - r0)) == r]
            if got:
                return np.concatenate(got)
        return None


OSM_HALF_WIDTH_M = {"motorway": 14.0, "trunk": 12.0, "primary": 10.0, "secondary": 9.0, "tertiary": 8.0,
                    "motorway_link": 7.0, "trunk_link": 7.0, "primary_link": 7.0, "residential": 6.0,
                    "service": 5.0, "footway": 3.0, "cycleway": 3.0, "path": 3.0, "pedestrian": 4.0}
LANE_M = 3.6


def osm_bridge_lines(elements):
    """[(WGS84 LineString, half width m)] of OSM bridge ways (bridge != "no")
    carrying a highway or railway: the width tag, else lanes x LANE_M plus a
    shoulder, else by highway type; rail RAIL_HALF_WIDTH_M."""
    from shapely.geometry import LineString

    out = []
    for e in elements:
        t = e.get("tags", {})
        if t.get("bridge", "no") == "no" or not e.get("geometry") or len(e["geometry"]) < 2:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in e["geometry"]])
        half = None
        try:
            half = float(str(t["width"]).split()[0]) / 2
        except (KeyError, ValueError, IndexError):
            pass
        if half is None and "lanes" in t:
            try:
                half = (int(str(t["lanes"]).split(";")[0]) * LANE_M + 4.0) / 2
            except ValueError:
                pass
        if half is None:
            half = RAIL_HALF_WIDTH_M if "railway" in t else OSM_HALF_WIDTH_M.get(t.get("highway"), DEFAULT_HALF_WIDTH_M)
        out.append((line, half))
    return out


def lines_for(cfg, frame):
    """[(local-m LineString, half width m)] of the area's City street
    centerlines, expressways and rail lines (data/raw/<area>_streets,
    _highways, _rail.geojson)."""
    from shapely.geometry import LineString, shape

    from .sources import RAW

    out = []

    def add(path, width_of):
        if not path.exists():
            return
        for f in json.loads(path.read_text())["features"]:
            if not f.get("geometry"):
                continue
            g = shape(f["geometry"])
            for ln in getattr(g, "geoms", [g]):
                if ln.geom_type != "LineString" or len(ln.coords) < 2:
                    continue
                lon, lat = np.asarray(ln.coords).T[:2]
                e, n = frame.to_local(lon, lat)
                out.append((LineString(np.column_stack([e, n])), width_of(f["properties"])))

    def street_width(p):
        c = p.get("class")
        if "RAMP" in str(p.get("st_type", "")) or "RAMP" in str(p.get("stname", "")):
            return RAMP_HALF_WIDTH_M
        return CLASS_HALF_WIDTH_M.get(c, DEFAULT_HALF_WIDTH_M)

    add(RAW / f"{cfg['name']}_streets.geojson", street_width)
    add(RAW / f"{cfg['name']}_highways.geojson", street_width)
    add(RAW / f"{cfg['name']}_rail.geojson", lambda p: RAIL_HALF_WIDTH_M)
    add(RAW / f"{cfg['name']}_rail_el.geojson", lambda p: RAIL_HALF_WIDTH_M)
    # OSM bridges: the New Jersey halves of the Delaware bridges and footbridges
    osm = RAW / f"{cfg['name']}_bridges.json"
    if osm.exists():
        for ln, half in osm_bridge_lines(json.loads(osm.read_text())["elements"]):
            lon, lat = np.asarray(ln.coords).T[:2]
            e, n = frame.to_local(lon, lat)
            out.append((LineString(np.column_stack([e, n])), half))
    return out


def water_local(cfg, frame):
    """NHD and PWD water polygons of the area, local m."""
    import shapely
    from shapely.geometry import shape
    from shapely.ops import unary_union

    from .sources import RAW

    polys = []
    for suffix in ("water_nhd", "water"):
        p = RAW / f"{cfg['name']}_{suffix}.geojson"
        if p.exists():
            polys += [shape(f["geometry"]).buffer(0) for f in json.loads(p.read_text())["features"] if f.get("geometry")]
    u = unary_union(polys)
    return shapely.transform(u, lambda c: np.column_stack(frame.to_local(c[:, 0], c[:, 1])))


DECK_SHRINK = 0.8  # the hard deck mask uses this share of the half width


def deck_screen(cfg, frame, cam, x_origin: float, y_origin: float):
    """Bridge decks where the render has them (water level, no sweep), at
    DECK_SHRINK of their half widths, mosaic px: never repainted."""
    import shapely
    from shapely.affinity import translate
    from shapely.geometry import Polygon

    lines = [(ln, h * DECK_SHRINK) for ln, h in lines_for(cfg, frame)]
    deck = deck_geometry(lines, water_local(cfg, frame), margin_m=0.0)
    if deck.is_empty:
        return Polygon()
    s = shapely.transform(deck, lambda c: np.column_stack(cam.world_to_screen(c[:, 0], c[:, 1], 0.0)))
    return translate(s, -x_origin, -y_origin)


def band_geometry(cfg, frame, cam, x_origin: float, y_origin: float):
    """Bridge bands in mosaic px: deck_geometry over the area's water, swept
    on screen from SWEEP_LOW_M to SWEEP_HIGH_M."""
    import shapely
    from shapely.affinity import translate
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    deck = deck_geometry(lines_for(cfg, frame), water_local(cfg, frame))
    if deck.is_empty:
        return Polygon()

    def scr(h):
        return shapely.transform(deck, lambda c: np.column_stack(cam.world_to_screen(c[:, 0], c[:, 1], h)))

    lo, hi = scr(SWEEP_LOW_M), scr(SWEEP_HIGH_M)
    # The sweep is a straight screen translation: the hull of lo and hi per
    # part is the swept band
    parts = []
    for a, b in zip(getattr(lo, "geoms", [lo]), getattr(hi, "geoms", [hi])):
        parts.append(unary_union([a, b]).convex_hull if a.area < 4e5 else unary_union([a, b]))
    return translate(unary_union(parts), -x_origin, -y_origin)
