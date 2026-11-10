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


def _near_palette(drawing: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Pixels of the drawing within COLOR_TOL (max channel) of a palette color."""
    d = drawing.astype(int)
    near = np.zeros(drawing.shape[:2], bool)
    for c in pal:
        near |= np.abs(d - c).max(axis=2) < COLOR_TOL
    return near


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
    near = _near_palette(drawing, _palette(sample))
    drawn = near | ~band  # outside the band, the drawing check doesn't apply
    drawn = _filter(_filter(drawn, ImageFilter.MaxFilter(CLOSE_PX)), ImageFilter.MinFilter(CLOSE_PX))
    out = water.copy()
    out[band] = water[band] & drawn[band]
    if deck is not None:
        # The deck itself, where the render has it: never water (dark asphalt
        # and its shadow can be the drawn river's colors)
        out &= ~deck
    return out


def refine_members(water: np.ndarray, drawing: np.ndarray, zone: np.ndarray,
                   sample: np.ndarray | None = None) -> np.ndarray:
    """The repaint's water mask made drawing-aware in a modeled bridge's
    members zone (structure_zones: cable buffers and the hanger zone). As in
    refine, a pixel there is river if the drawing used a drawn-river color
    for it (COLOR_TOL of the sample's palette); a pixel that isn't stays as
    drawn only if it belongs to a stroke connected to something the repaint
    keeps (the deck, towers, land, or the render's tubes the caller left out
    of `water`), so hangers and the cable survive while ripple dashes and
    stray specks in the drawn river are repainted.

    No closing, unlike refine: hangers are 2-3 px strokes about 15 px apart,
    and CLOSE_PX would fill them in as river. The connectivity test does the
    closing's job of dropping isolated specks.

    sample: as in refine. Without one, the zone keeps the drawing."""
    if not zone.any() or not water.any():
        return water
    if sample is None:
        sample = ring_sample(water, drawing, zone)
    if sample is None or len(sample) == 0:
        return water & ~zone
    near = _near_palette(drawing, _palette(sample))
    strokes = _connected_to(zone & ~near & water, ~water)
    out = water.copy()
    out[zone] = water[zone] & ~strokes[zone]
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
    # Bridges modeled in 3D (config/bridge_structures.json, "bridge_structures":
    # true) get structure_protect instead: their band and water-level deck
    # mask assume a deck at y = 0. Every line on them is clipped out, City
    # centerlines and rail included
    return clip_lines(out, structure_corridor_for(cfg, frame))


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


# --- Elevated decks in the scene and their shadows on the river (Nov. 9) ---
# Stephen: the Ben Franklin and Walt Whitman bridges "look awful"; the Walt
# Whitman "has buildings on the roadway." Both causes are in the render, not
# the repaint:
# (1) The 2022 LiDAR saw the elevated decks. City centerlines don't carry
#     the DRPA spans at full width, so the structure highway mask missed
#     them, and the scene extruded deck cells as blocks: structure s1745,
#     about 5,400 m2 at 47-59 m on the WWB main span; s580/s589 (38-42 m) on
#     the BFB; footprint 326703's parts stepping up to 40 m where the WWB
#     approach crosses the Packer Ave terminal.
# (2) The 2024 aerial has each bridge's long shadow on the river. The model
#     draws it as a gray slab with a ghost bridge in it, and the band keeps
#     it from the repaint.

DECK_HIGHWAYS = ("motorway", "motorway_link", "trunk", "trunk_link")
# OSM draws these decks one way per carriageway (the BFB and WWB: 3 or 4
# lanes each, oneway), so osm_bridge_lines' half width (lanes x 3.6 m plus
# shoulders) covers only that carriageway. The pad reaches the rest of the
# deck: the BFB is about 39 m wide with PATCO's tracks and the walkways
# outside the roadway, so its outer edge is ~17-18 m from a carriageway's
# centerline (4 lanes: 9.2 m + 8 m)
DECK_PAD_M = 8.0
# A LiDAR-shaped footprint part this tall, mostly inside a deck corridor, is
# the deck the LiDAR saw above the footprint, not the building. The Packer
# Ave terminal (326703) has real roofs up to ~12 m off the deck, while its
# parts under the WWB approach step 10-40 m up the ramp; parts under 10 m
# stay, since a real roof edge can sit under a deck's edge
DECK_PART_MIN_H_M = 10.0
DECK_PART_SHARE = 0.5


def deck_corridors(elements, to_local, pad_m: float = DECK_PAD_M) -> list:
    """Local-m polygons of OSM motorway and trunk bridge ways (bridge != "no"):
    each way buffered by its osm_bridge_lines half width plus pad_m.
    to_local: (lon array, lat array) -> (e, n). Street, foot and rail bridges
    are left out: they're low, and rail already has its own mask."""
    from shapely.geometry import LineString

    sel = [e for e in elements if e.get("tags", {}).get("highway") in DECK_HIGHWAYS]
    out = []
    for ln, half in osm_bridge_lines(sel):
        lon, lat = np.asarray(ln.coords).T[:2]
        e, n = to_local(lon, lat)
        out.append(LineString(np.column_stack([e, n])).buffer(half + pad_m))
    return out


def deck_corridors_for(cfg, frame) -> list:
    """deck_corridors of data/raw/<area>_bridges.json (04p_fetch_bridges.py),
    [] when the area has no file."""
    from .sources import RAW

    path = RAW / f"{cfg['name']}_bridges.json"
    if not path.exists():
        return []
    return deck_corridors(json.loads(path.read_text())["elements"], frame.to_local)


def _is_footprint_part(pid) -> bool:
    a, sep, b = str(pid).partition("-")
    return bool(sep) and a.isdigit() and b.isdigit()


def drop_deck_parts(buildings, corridors, min_h: float = DECK_PART_MIN_H_M, share: float = DECK_PART_SHARE):
    """(kept, dropped). LiDAR-shaped footprint parts ("<footprint>-<k>") at
    least `share` inside a deck corridor and at least min_h tall are the deck
    seen from above, and are dropped; the footprint's other parts stay.
    Single-height footprints, structures (masked upstream) and vessels pass."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    if not corridors:
        return list(buildings), []
    corr = unary_union(corridors)
    tree = STRtree(list(getattr(corr, "geoms", [corr])))
    kept, dropped = [], []
    for b in buildings:
        if b.get("h", 0) < min_h or not _is_footprint_part(b.get("id")):
            kept.append(b)
            continue
        g = unary_union([Polygon(p[0], p[1:]).buffer(0) for p in b["polys"]])
        if g.is_empty or not len(tree.query(g, predicate="intersects")):
            kept.append(b)
            continue
        (dropped if g.intersection(corr).area >= share * g.area else kept).append(b)
    return kept, dropped


# Shadows: a pixel of river darker than this share of the zone's median
# river luminance. In the 2024 aerial the Delaware is mid-brown (luma ~100)
# and the bridge shadows near-black (~35-45); ripple troughs stay above ~75
SHADOW_RATIO = 0.62
SHADOW_OPEN_PX = 1  # single dark ripple pixels; 2 erased the cables' 3-4 px shadows
SHADOW_GROW_PX = 4  # the penumbra past the mid-dark edge; 2 left a dark rim along each filled line
SHADOW_BRIGHT_MAX = 1.5
# Mid-dark: the shadow's soft edge and hanger lines. The Ben Franklin's
# hanger shadows measured ~0.92 of the river, so 0.90 missed them and their
# outline stayed in the Nov. 9 render
# (output/review/bridges/nj/render_v2/bfb_mid.jpg). Ripple troughs dip to
# ~0.85 too, but only go where they touch a shadow
SHADOW_WEAK_RATIO = 0.95
# Closing radius: hangers fall ~40 px apart, so the lit river between them
# is shut into one region with the hanger lines. Filling the lines alone
# left each one's edge visible as a faint lattice (same render)
SHADOW_CLOSE_PX = 40
SHADOW_SOURCE_TOL = 40  # max channel distance from the zone's median river color


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 box, edges clamped (summed-area table)."""
    pad = np.pad(a, ((r + 1, r), (r + 1, r)) + ((0, 0),) * (a.ndim - 2), mode="edge")
    c = pad.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def _close(m: np.ndarray, r: int) -> np.ndarray:
    """Binary closing of `m` with a (2r+1)^2 square, from box sums so the
    cost doesn't grow with r. Edges clamp as in _box_mean."""
    grown = _box_mean(m.astype(np.float64), r) > 1e-9
    return _box_mean(grown.astype(np.float64), r) >= 1 - 1e-9


def _fill_from(rgb: np.ndarray, valid: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Smooth color field over `hole` from the `valid` pixels around it
    (normalized box averages at growing radii, on a 1/4 grid), full res."""
    H, W = valid.shape
    f = 4 if min(H, W) >= 64 else 1
    h, w = -(-H // f), -(-W // f)
    pad = ((0, h * f - H), (0, w * f - W))
    v = np.pad(valid, pad).reshape(h, f, w, f).mean(axis=(1, 3))
    c = np.stack([np.pad(rgb[..., i].astype(np.float64) * valid, pad).reshape(h, f, w, f).mean(axis=(1, 3))
                  for i in range(3)], axis=-1)
    field = np.full((h, w, 3), np.nan)
    for r in (2, 6, 16, 40, 100, 250, max(h, w)):
        den = _box_mean(v, r)
        num = _box_mean(c, r)
        ok = np.isnan(field[..., 0]) & (den > 0.05)
        field[ok] = num[ok] / den[ok, None]
        if not np.isnan(field[..., 0]).any():
            break
    field = np.nan_to_num(field, nan=0.0)
    up = np.stack([np.asarray(Image.fromarray(field[..., i].astype(np.float32)).resize((w * f, h * f),
                                                                                       Image.BILINEAR))
                   for i in range(3)], axis=-1)[:H, :W]
    return up


def _connected_to(weak: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """Pixels of `weak` in 8-connected components that touch `seed`."""
    from rasterio.features import rasterize, shapes

    if not weak.any() or not seed.any():
        return np.zeros(weak.shape, bool)
    m = (weak | seed).astype(np.uint8)
    comps = [(g, i + 1) for i, (g, _) in enumerate(shapes(m, mask=m.astype(bool), connectivity=8))]
    label = rasterize(comps, out_shape=weak.shape, fill=0, dtype="int32", all_touched=False)
    keep = np.unique(label[seed])
    keep = keep[keep > 0]
    return weak & np.isin(label, keep)


def clear_water_shadows(rgb: np.ndarray, water: np.ndarray, zone: np.ndarray, protect: np.ndarray,
                        ratio: float = SHADOW_RATIO):
    """(rgb with bridge shadows on the river filled, shadow mask). Shadow:
    water pixels in `zone` (near a deck, outside the deck itself), not
    `protect` (vessels, piers), darker than `ratio` x the zone's median river
    luminance (plus mid-dark pixels under SHADOW_WEAK_RATIO connected to
    them); opened SHADOW_OPEN_PX, grown SHADOW_GROW_PX, closed
    SHADOW_CLOSE_PX, all kept to the zone. Filled with a smooth field of
    the surrounding river's color. Nothing outside the mask changes."""
    rgb = np.asarray(rgb)
    cand_zone = water & zone & ~protect
    if not cand_zone.any():
        return rgb.copy(), np.zeros(water.shape, bool)
    luma = rgb[..., :3].astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    med = float(np.median(luma[cand_zone]))
    dark = cand_zone & (luma < ratio * med)
    o = 2 * SHADOW_OPEN_PX + 1
    dark = _filter(_filter(dark, ImageFilter.MinFilter(o)), ImageFilter.MaxFilter(o)) & dark
    # Hysteresis: the shadow's soft edge and the thin hanger and cable lines
    # running off it are only mid-dark; they go when connected to the core
    dark |= _connected_to(cand_zone & (luma < SHADOW_WEAK_RATIO * med), dark)
    mask = _filter(dark, ImageFilter.MaxFilter(2 * SHADOW_GROW_PX + 1)) & cand_zone
    # Closing: one region over a hanger lattice, gaps and all (see
    # SHADOW_CLOSE_PX). Box sums, not PIL Max/MinFilter: an 81 px PIL kernel
    # is O(k^2) per pixel and far too slow on a 9216 x 5632 frame.
    # & cand_zone so it never spreads onto land, the deck or a vessel/pier
    mask = (mask | _close(mask, SHADOW_CLOSE_PX)) & cand_zone
    if not mask.any():
        return rgb.copy(), mask
    # River to fill from: in the zone (not the deck), not a vessel or pier,
    # not shadow, and not much brighter than river (glints, wakes, piers
    # missing from OSM)
    river = cand_zone & ~mask & (luma >= ratio * med) & (luma <= SHADOW_BRIGHT_MAX * med)
    # ...and river-colored: the deck's lit outer edge (walkways, PATCO)
    # sits on mapped water too, and tinted the fill blue-gray beside it
    med_rgb = np.median(rgb[..., :3][river], axis=0) if river.any() else None
    if med_rgb is not None:
        river &= np.abs(rgb[..., :3].astype(np.int16) - med_rgb.astype(np.int16)).max(axis=2) <= SHADOW_SOURCE_TOL
    # Smooth field only. Adding the shadow's own ripples back (brightened
    # to match) engraved the tower, cable and hanger edges into the fill:
    # the faint outline in the Nov. 9 render (bfb_mid.jpg)
    filled = _fill_from(rgb[..., :3], river, mask)
    out = rgb.copy()
    out[..., :3][mask] = np.clip(np.round(filled[mask]), 0, 255).astype(np.uint8)
    return out, mask


# Suspension-bridge towers (Nov. 9). The decks' LiDAR shapes are dropped
# (drop_deck_parts) and the 2024 aerial sees each tower only from above, so
# the model drew the Ben Franklin with one tower and the Walt Whitman with
# none (output/review/bridges/nj/gpu_test/final_bfb.jpg, final_wwb.jpg).
# config/bridge_towers.json names each tower's OSM way, published height and
# approximate paint color.
BRIDGE_TOWERS = "bridge_towers.json"  # under config/


def tower_legs(osm_elements, entries, to_local) -> list:
    """Two square legs per tower entry, as scene buildings
    {"id": "tower-<entry id>-a" / "-b", "h", "fixed_color", "polys"}.

    Each OSM tower outline is a thin strip across the deck (~31-35 x 3-6 m).
    Extruded whole to ~116 m it would read as a building wall, so it is drawn
    as its two legs: a square as wide as the strip at each end of the strip's
    long axis, inside the strip. No source gives the leg dimensions; the leg
    size is an estimate. No "facade" key: plain steel walls, no windows.
    fixed_color makes colored() skip the aerial sample, which only sees the
    tower top. to_local: (lon array, lat array) -> (e, n) in local meters.
    Raises KeyError when an entry's OSM way is missing, so a stale raw file
    can't silently drop a tower."""
    from shapely.geometry import Polygon

    ways = {e.get("id"): e for e in osm_elements if e.get("type", "way") == "way"}
    out = []
    for entry in entries:
        way = ways.get(entry["osm_way"])
        if way is None or not way.get("geometry"):
            raise KeyError(f"bridge tower {entry['id']}: OSM way {entry['osm_way']} not in the raw file "
                           "(re-run scripts/04q_fetch_bridge_towers.py)")
        lon = np.array([p["lon"] for p in way["geometry"]], dtype=float)
        lat = np.array([p["lat"] for p in way["geometry"]], dtype=float)
        e, n = to_local(lon, lat)
        rect = Polygon(np.column_stack([e, n])).minimum_rotated_rectangle
        c = np.asarray(rect.exterior.coords)[:4]
        # Start the corners on a long side: c0 -> c1 runs along the strip
        if np.hypot(*(c[1] - c[0])) < np.hypot(*(c[2] - c[1])):
            c = np.roll(c, -1, axis=0)
        length = np.hypot(*(c[1] - c[0]))
        width = np.hypot(*(c[3] - c[0]))
        if length < 2 * width:
            raise ValueError(f"bridge tower {entry['id']}: outline {length:.1f} x {width:.1f} m is not a strip; "
                             "two square legs would overlap")
        # Leg side: the strip width, or min_leg_m (an estimate) when the
        # strip is thinner; the Walt Whitman's 3.3 m strips drew as needles
        side = max(width, float(entry.get("min_leg_m", 0.0)))
        along = (c[1] - c[0]) / length
        across = (c[3] - c[0]) / width
        mid = c[0] + across * width / 2  # strip center line, at the "a" end
        a0 = mid - across * side / 2
        b0 = mid + along * (length - side) - across * side / 2
        u, v = along * side, across * side
        legs = {"a": [a0, a0 + u, a0 + u + v, a0 + v],
                "b": [b0, b0 + u, b0 + u + v, b0 + v]}
        for k, ring in legs.items():
            out.append({"id": f"tower-{entry['id']}-{k}", "h": entry["height_m"],
                        "fixed_color": list(entry["color"]),
                        "polys": [[np.round(np.asarray(ring), 2).tolist()]]})
    return out


def tower_legs_for(cfg, frame) -> list:
    """tower_legs for the area's entries in config/bridge_towers.json and the
    OSM outlines in data/raw/<area>_bridge_towers.json
    (scripts/04q_fetch_bridge_towers.py); [] unless the area config has
    "bridge_towers": true. A configured area with no raw file raises, like a
    missing way does."""
    if not cfg.get("bridge_towers"):
        return []
    from .projection import REPO_ROOT
    from .sources import RAW

    entries = [e for e in json.loads((REPO_ROOT / "config" / BRIDGE_TOWERS).read_text())["entries"] if e.get("area") == cfg["name"]]
    if not entries:
        return []
    elements = json.loads((RAW / f"{cfg['name']}_bridge_towers.json").read_text())["elements"]
    return tower_legs(elements, entries, frame.to_local)


# --- Suspension structure (Nov. 9) ---
# Tower legs alone left the Ben Franklin and Walt Whitman as two pairs of
# posts over a flat aerial deck. suspension_structure adds the rest: a
# raised deck in ~10 m steps with lane lines, tower crossbeams, the two main
# cables, hangers and, on the Ben Franklin, the Warren stiffening truss that
# rises above the deck. config/bridge_structures.json holds every dimension
# with its source, or marks it an estimate with a reason.
#
# Bridge frame: s runs along the line from tower A's center to tower B's
# (the midpoints of each tower's OSM leg pair), t across it. The deck is
# centered on that line rather than on the OSM carriageways: the suspended
# deck hangs between the cables by construction, and the OSM carriageways'
# midline drifts 1.3-1.8 m (Ben Franklin) and 0.9-5.8 m (Walt Whitman) off
# it, which would put the deck under one cable. The 2022 LiDAR deck is
# centered on the tower line within ~1 m. The OSM deck ways are still
# required (a stale raw file fails loudly) and their offset is reported.
#
# Heights are meters above mean high water, the datum of the published
# tower heights and clearances; the scene's water and ground are at 0.
BRIDGE_STRUCTURES = "bridge_structures.json"  # under config/
LIDAR_MIN_SHARE = 0.5  # a profile bin needs returns in half its cells (the grid edge cuts the WWB's NJ end)
MIN_HANGER_M = 1.0  # shorter hangers (where the cable meets the deck) are left out


def _dims(entry) -> dict:
    """{key: value} of an entry's dims; each is {"value": ...} with a source
    or an estimate flag."""
    return {k: d["value"] for k, d in entry["dims"].items()}


def vertical_curve(s, s_mid: float, z_mid: float, half_len: float, end_grade: float):
    """Symmetric parabolic crest: z_mid at s_mid, falling at end_grade
    (m/m) half_len away. The fallback deck where the LiDAR has no returns."""
    s = np.asarray(s, dtype=float)
    return z_mid - end_grade / (2.0 * half_len) * (s - s_mid) ** 2


def lidar_profile(lidar, a, u, s0: float, s1: float, bin_m: float = 20.0, half_m: float = 5.0, datum_m: float = 0.0):
    """(bin centers s, median LiDAR surface height minus datum_m, NaN where
    a bin has returns in fewer than LIDAR_MIN_SHARE of its cells) along the
    line a + u*s, over cells within half_m of it. lidar: {"dsm" (row 0 =
    north edge), "origin" (west, north), "res"}. The median of the
    first-return surface ignores the few cells with trucks, lamp posts or a
    hanger in them."""
    centers = np.arange(s0 + bin_m / 2, s1, bin_m)
    out = np.full(centers.size, np.nan)
    if lidar is None:
        return centers, out
    dsm, (west, north), res = lidar["dsm"], lidar["origin"], float(lidar["res"])
    a, u = np.asarray(a, float), np.asarray(u, float)
    v = np.array([-u[1], u[0]])
    corners = np.array([a + u * s + v * t for s in (s0, s1) for t in (-half_m, half_m)])
    c0 = max(int(np.floor((corners[:, 0].min() - west) / res)), 0)
    c1 = min(int(np.ceil((corners[:, 0].max() - west) / res)), dsm.shape[1])
    r0 = max(int(np.floor((north - corners[:, 1].max()) / res)), 0)
    r1 = min(int(np.ceil((north - corners[:, 1].min()) / res)), dsm.shape[0])
    if c1 <= c0 or r1 <= r0:
        return centers, out
    ee, nn = np.meshgrid(west + (np.arange(c0, c1) + 0.5) * res, north - (np.arange(r0, r1) + 0.5) * res)
    s = (ee - a[0]) * u[0] + (nn - a[1]) * u[1]
    t = (ee - a[0]) * v[0] + (nn - a[1]) * v[1]
    sub = dsm[r0:r1, c0:c1]
    inside = (np.abs(t) <= half_m) & (s >= s0) & (s < s0 + centers.size * bin_m)
    idx = ((s[inside] - s0) // bin_m).astype(int)
    z = sub[inside].astype(float)
    expected = bin_m * 2 * half_m / res ** 2  # cells in a full bin, wherever the grid has them
    for i in range(centers.size):
        zi = z[idx == i]
        zi = zi[np.isfinite(zi)]
        if zi.size >= LIDAR_MIN_SHARE * expected:
            out[i] = float(np.median(zi)) - datum_m
    return centers, out


def _parabola(s, s0: float, z0: float, s1: float, z1: float, sag: float):
    """Cable between (s0, z0) and (s1, z1) hanging `sag` below the chord at
    mid-span: the shape of a cable under a load uniform along the span."""
    x = (np.asarray(s, float) - s0) / (s1 - s0)
    return z0 + (z1 - z0) * x - 4.0 * sag * x * (1.0 - x)


def _rect(p0, p1, v, half):
    """Ring of the rectangle from p0 to p1, half wide along unit v."""
    return np.round(np.array([p0 - v * half, p1 - v * half, p1 + v * half, p0 + v * half]), 2).tolist()


def _rect_t(p0, p1, v, t0, t1):
    """Ring of the band t0..t1 across v from p0 to p1."""
    return np.round(np.array([p0 + v * t0, p1 + v * t0, p1 + v * t1, p0 + v * t1]), 2).tolist()


def _r(x):
    return round(float(x), 3)


def _osm_midline_offset(lines, a, u, s0, s1, step=50.0):
    """(mean, max) |t| of the OSM carriageways' midline (halfway between the
    outermost carriageway crossings of each cross-section) off the tower
    line, or None when no way crosses the structure."""
    from shapely.geometry import LineString

    v = np.array([-u[1], u[0]])
    offs = []
    for s in np.arange(s0, s1 + 1e-9, step):
        p = a + u * s
        cut = LineString([p - v * 80, p + v * 80])
        ts = []
        for ln in lines:
            x = cut.intersection(ln)
            for g in getattr(x, "geoms", [x]):
                if not g.is_empty:
                    ts.append(float((np.asarray(g.coords[0]) - a) @ v))
        if ts:
            offs.append((min(ts) + max(ts)) / 2)
    if not offs:
        return None
    offs = np.abs(offs)
    return round(float(offs.mean()), 2), round(float(offs.max()), 2)


def _values(cfg: dict) -> dict:
    """{key: value} of a config block whose entries are plain values or
    {"value", "estimate"/"source", ...} records."""
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in cfg.items()}


def _lanes(way, default: int = 2) -> int:
    try:
        return int(str(way.get("tags", {})["lanes"]).split(";")[0])
    except (KeyError, ValueError):
        return default


# --- Approach spans past the anchorages (Nov. 9) ---
# The modeled deck stopped at the anchorages, ~33-40 m up, while the aerial
# road ran on at grade below it; the 2022 LiDAR shows the approaches still
# descending (the Walt Whitman ~37 m up 400 m past its PA anchorage, at
# grade ~1.5 km out). approach_decks follows the OSM deck ways out from each
# anchorage in segment_m steps.
#
# Vertical frame. The main structure is in meters above mean high water
# (NOAA 8545240: 0.972 m NAVD88): the scene's y = 0 is the river, whose
# 2022 LiDAR surface is -1.2..+0.8 m NAVD88, so the river plane and MHW
# agree within ~1-2 m. On land the scene's y = 0 is the local ground, and
# every building's height is LiDAR surface minus LiDAR ground; the ground
# under the approaches is 2-4 m NAVD88 by the river and ~10-12 m in Old City
# (Ben Franklin, PA end). So an approach's height is LiDAR deck minus a
# datum that starts at MHW at the anchorage (no step where it meets the
# main deck) and blends linearly to the local ground over datum_blend_m.
APPROACH_MIN_CLEAR_M = 0.5  # a deck underside lower than this stands on the ground
APPROACH_REACH_M = 100.0  # how far across the axis a cross-section looks for the carriageways
APPROACH_MAX_M = 5000.0
APPROACH_MIN_GROUND_CELLS = 50


def _cells(grid, corners):
    """(e, n, z) of the grid cells in the bounding box of `corners` (local
    m), or None when the box misses the grid."""
    if grid is None:
        return None
    arr, (west, north), res = grid["dsm"], grid["origin"], float(grid["res"])
    corners = np.asarray(corners, float)
    c0 = max(int(np.floor((corners[:, 0].min() - west) / res)), 0)
    c1 = min(int(np.ceil((corners[:, 0].max() - west) / res)), arr.shape[1])
    r0 = max(int(np.floor((north - corners[:, 1].max()) / res)), 0)
    r1 = min(int(np.ceil((north - corners[:, 1].min()) / res)), arr.shape[0])
    if c1 <= c0 or r1 <= r0:
        return None
    ee, nn = np.meshgrid(west + (np.arange(c0, c1) + 0.5) * res, north - (np.arange(r0, r1) + 0.5) * res)
    return ee.ravel(), nn.ravel(), arr[r0:r1, c0:c1].astype(float).ravel()


def _crossings(carriageways, p, v, reach: float = APPROACH_REACH_M):
    """[(t, half width, lanes)] where the cross-section through p (along v)
    meets each carriageway, sorted by t (offset along v from p)."""
    from shapely.geometry import LineString

    cut = LineString([p - v * reach, p + v * reach])
    out = []
    for ln, half, lanes in carriageways:
        x = cut.intersection(ln)
        for g in getattr(x, "geoms", [x]):
            if not g.is_empty and g.geom_type == "Point":
                out.append((float((np.asarray(g.coords[0]) - p) @ v), float(half), int(lanes)))
    return sorted(out)


def _running_median3(z):
    """3-point running median where all three are finite (sign gantries and
    trucks over one 10 m segment)."""
    out = z.copy()
    for i in range(1, len(z) - 1):
        w = z[i - 1:i + 2]
        if np.isfinite(w).all():
            out[i] = float(np.median(w))
    return out


def approach_decks(carriageways, ca, u, s_from: float, sign: float, top_from: float, width_from: float, lidar,
                   ground, mhw_m: float, cfg: dict, seg_m: float, half_m: float, look: dict):
    """(parts, qa) of one approach: the deck continuing from the main deck's
    end at s_from (on the tower axis ca + u*s), outward (sign -1 or +1).

    carriageways: [(local LineString, OSM half width, lanes)] of the OSM
    deck ways. At each station (every seg_m along the axis) a cross-section
    finds the carriageways; the deck runs centered between the outermost
    ones, as wide as their spread plus the main deck's margin beyond them
    at the anchorage (width_from), so the two meet flush. Its top is the
    median 2022 LiDAR surface within half_m of the carriageways (3-point
    running median), minus a datum blending from mhw_m at the anchorage to
    the local LiDAR ground (median within ground_radius_m) over
    datum_blend_m (see the note above). Where the LiDAR has no returns the
    top falls at fallback_grade from the last measured point (an
    estimate). The approach ends where the deck is less than
    stop_above_ground_m above the ground ("at_grade"), where the OSM deck
    ways end ("osm_end"), or where they spread more than max_spread_m
    ("diverge"). Segments float on deck_thickness_m; a pier (deck width x
    pier_length_m, ground to the deck underside) stands every
    pier_spacing_m. Lane lines per carriageway: OSM lanes at LANE_M, solid
    edges, dashed between.

    parts: [(part, ring, z0, h, wall rgb, roof rgb or None)]."""
    v = np.array([-u[1], u[0]])
    spacing = float(cfg["pier_spacing_m"])
    thick = float(cfg["deck_thickness_m"])
    stop = float(cfg["stop_above_ground_m"])
    grade = float(cfg["fallback_grade"])
    blend = float(cfg["datum_blend_m"])
    radius = float(cfg["ground_radius_m"])
    max_spread = float(cfg["max_spread_m"])

    # Stations and their carriageway crossings
    stations, end = [], "osm_end"
    for k in range(int(APPROACH_MAX_M / seg_m) + 1):
        s = s_from + sign * k * seg_m
        cr = _crossings(carriageways, ca + u * s, v)
        if not cr:
            break
        if cr[-1][0] - cr[0][0] > max_spread:
            end = "diverge"
            break
        stations.append((s, cr))
    qa = {"segments": 0, "end": end, "length_m": 0.0, "piers": 0, "fallback_segments": 0}
    if len(stations) < 2:
        return [], qa
    spread0 = stations[0][1][-1][0] - stations[0][1][0][0]
    edge = max((width_from - spread0) / 2, max(h for _, h, _ in stations[0][1]))

    def mid_width(cr):
        lo, hi = cr[0][0], cr[-1][0]
        return (lo + hi) / 2, (hi - lo) + 2 * edge

    def pt(s, t):
        return ca + u * s + v * t

    # LiDAR deck and local ground per segment
    nseg = len(stations) - 1
    dsm = np.full(nseg, np.nan)
    gnd = np.full(nseg, np.nan)
    for i in range(nseg):
        (s0, c0), (s1, c1) = stations[i], stations[i + 1]
        tm0, w0 = mid_width(c0)
        tm1, w1 = mid_width(c1)
        quad = [pt(s0, tm0 - w0 / 2), pt(s1, tm1 - w1 / 2), pt(s1, tm1 + w1 / 2), pt(s0, tm0 + w0 / 2)]
        got = _cells(lidar, quad)
        if got is not None:
            ee, nn, z = got
            cs = (ee - ca[0]) * u[0] + (nn - ca[1]) * u[1]
            ct = (ee - ca[0]) * v[0] + (nn - ca[1]) * v[1]
            f = (cs - s0) / (s1 - s0)
            inside = (f >= 0) & (f < 1)
            paired = len(c0) == len(c1)
            near = np.zeros(z.shape, bool)
            for j, (t0, _, _) in enumerate(c0):
                t1 = c1[j][0] if paired else t0
                near |= np.abs(ct - (t0 + (t1 - t0) * f)) <= half_m
            zz = z[inside & near]
            zz = zz[np.isfinite(zz)]
            expected = seg_m * 2 * half_m * len(c0) / float(lidar["res"]) ** 2
            if zz.size >= LIDAR_MIN_SHARE * expected:
                dsm[i] = float(np.median(zz))
        p_mid = pt((s0 + s1) / 2, (tm0 + tm1) / 2)
        got = _cells(ground, [p_mid - radius, p_mid + radius])
        if got is not None:
            g = got[2][np.isfinite(got[2])]
            if g.size >= APPROACH_MIN_GROUND_CELLS:
                gnd[i] = float(np.median(g))
    dsm = _running_median3(dsm)

    # Walk outward until the deck reaches the ground
    tops = []
    last_g = np.nan
    anchor_s, anchor_top = s_from, top_from
    for i in range(nseg):
        s_mid = (stations[i][0] + stations[i + 1][0]) / 2
        dist = abs(s_mid - s_from)
        if np.isfinite(gnd[i]):
            last_g = gnd[i]
        if np.isfinite(dsm[i]):
            if np.isfinite(last_g) and dsm[i] - last_g < stop:
                qa["end"] = "at_grade"
                break
            datum = mhw_m + (min(dist / blend, 1.0) * (last_g - mhw_m) if np.isfinite(last_g) else 0.0)
            top = dsm[i] - datum
            anchor_s, anchor_top = s_mid, top
        else:
            top = anchor_top - grade * abs(s_mid - anchor_s)
            qa["fallback_segments"] += 1
            if top < stop:
                qa["end"] = "at_grade"
                break
        tops.append(top)
    n = len(tops)
    if n == 0:
        return [], qa

    parts = []
    z0s = [t - thick if t - thick > APPROACH_MIN_CLEAR_M else 0.0 for t in tops]
    for i in range(n):
        (s0, c0), (s1, c1) = stations[i], stations[i + 1]
        tm0, w0 = mid_width(c0)
        tm1, w1 = mid_width(c1)
        ring = np.round(np.array([pt(s0, tm0 - w0 / 2), pt(s1, tm1 - w1 / 2), pt(s1, tm1 + w1 / 2),
                                  pt(s0, tm0 + w0 / 2)]), 2).tolist()
        parts.append(("approach", ring, _r(z0s[i]), _r(tops[i]), look["wall_rgb"], look["deck_rgb"]))

    # Piers at every pier_spacing_m from the anchorage, under floating decks
    every = max(int(round(spacing / seg_m)), 1)
    for j in range(every, n, every):
        z = min(z0s[j - 1], z0s[j])
        if z <= 0:
            continue
        s, cr = stations[j]
        tm, w = mid_width(cr)
        c = pt(s, tm)
        pl = float(cfg["pier_length_m"]) / 2
        ring = np.round(np.array([c - u * pl - v * w / 2, c + u * pl - v * w / 2, c + u * pl + v * w / 2,
                                  c - u * pl + v * w / 2]), 2).tolist()
        parts.append(("pier", ring, 0.0, _r(z), list(cfg["pier_rgb"]), list(cfg["pier_rgb"])))
        qa["piers"] += 1

    # Lane lines: per carriageway, where both stations of a segment see the
    # same carriageways. Dashes are laid out by distance from the anchorage
    lw, lh = look["lw"], look["lh"]
    period = look["dash"] + look["gap"]
    for i in range(n):
        (s0, c0), (s1, c1) = stations[i], stations[i + 1]
        if len(c0) != len(c1):
            continue
        d0, d1 = i * seg_m, (i + 1) * seg_m
        for (t0, _, lanes), (t1, _, _) in zip(c0, c1):
            road = lanes * LANE_M
            offs = [(-road / 2 + lw / 2, None), (road / 2 - lw / 2, None)]
            offs += [(-road / 2 + k * LANE_M, "dash") for k in range(1, lanes)]
            for off, kind in offs:
                pieces = [(d0, d1)]
                if kind == "dash":
                    k0 = int(np.floor(d0 / period))
                    pieces = [(max(d0, k * period), min(d1, k * period + look["dash"]))
                              for k in range(k0, int(np.ceil(d1 / period)) + 1)]
                for a, b in pieces:
                    if b - a <= 0.05:
                        continue
                    fa, fb = (a - d0) / seg_m, (b - d0) / seg_m
                    pa = pt(s0 + sign * (a - d0), t0 + (t1 - t0) * fa + off)
                    pb = pt(s0 + sign * (b - d0), t0 + (t1 - t0) * fb + off)
                    parts.append(("approach_lane", _rect(pa, pb, v, lw / 2), _r(tops[i]), _r(tops[i] + lh),
                                  look["lane_rgb"], None))
    qa.update(segments=n, length_m=round(n * seg_m, 1),
              top_m=[round(float(min(tops)), 2), round(float(max(tops)), 2)],
              end_top_m=round(float(tops[-1]), 2),
              end_above_ground_m=None if not np.isfinite(dsm[n - 1]) or not np.isfinite(last_g)
              else round(float(dsm[n - 1] - last_g), 2))
    return parts, qa


def tower_axis(osm_elements, tower_entries, to_local):
    """(center A, center B, legs) of a bridge's two towers from tower_legs:
    each center is the midpoint of its leg pair; legs[i] maps side (+1
    left of A->B, -1 right) to that leg's center."""
    from shapely.geometry import Polygon

    legs = tower_legs(osm_elements, tower_entries, to_local)
    by_tower = []
    for entry in tower_entries:
        cs = [np.asarray(Polygon(b["polys"][0][0]).centroid.coords[0]) for b in legs
              if b["id"].rsplit("-", 1)[0] == f"tower-{entry['id']}"]
        by_tower.append(cs)
    ca, cb = (np.mean(cs, axis=0) for cs in by_tower)
    u = (cb - ca) / np.linalg.norm(cb - ca)
    v = np.array([-u[1], u[0]])
    sides = [{int(np.sign((c - m) @ v)): c for c in cs} for cs, m in zip(by_tower, (ca, cb))]
    return ca, cb, sides


def suspension_structure(entry, osm_elements, tower_entries, to_local, water=None, lidar=None, mhw_m: float = 0.0,
                         method=None, ground=None) -> dict:
    """Scene geometry of one suspension bridge (config/bridge_structures.json
    entry): {"buildings": [...], "tubes": [...], "qa": {...}}, local meters.

    Buildings use the tower_legs shape plus "z0" (bottom; 0 = on the ground)
    and "roof_rgb" (flat top color): deck segments, lane lines, PATCO track
    beds, anchorage blocks, tower crossbeams. Tubes are {"id", "pts": [[e, n,
    z], ...], "r", "color"}: main cables, hangers, X-bracing, truss chords
    and diagonals. The tower legs themselves are tower_legs' (added by
    scripts/05_build_scene.py add_bridge_towers) and are not repeated.

    osm_elements: the tower outlines and the entry's osm_deck_ways (raises
    KeyError when one is missing). tower_entries: the two
    config/bridge_towers.json entries, A then B. water: shapely geometry in
    local m; a deck segment whose center is in it floats on its deck
    thickness, the rest stand on the ground (solid viaduct, anchorage).
    lidar: {"dsm", "origin", "res"} in NAVD88 m, or None; mhw_m: NAVD88
    height of mean high water. method: segment and sampling lengths and
    land_rule (see the deck below), config/bridge_structures.json "method".

    With "approach": true on the entry, the deck continues past each
    anchorage along the OSM deck ways as floating approach spans on piers
    (approach_decks; method["approach"] holds its parameters). ground: the
    LiDAR ground grid like `lidar`, for the approaches' local ground."""
    import shapely
    from shapely.geometry import LineString

    method = {"segment_m": 10.0, "profile_bin_m": 20.0, "profile_half_width_m": 5.0, "cable_step_m": 10.0,
              "land_rule": "anchorages", **(method or {})}
    d = _dims(entry)
    eid = entry["id"]
    ways = {e.get("id"): e for e in osm_elements if e.get("type", "way") == "way"}
    deck_lines, carriageways = [], []
    for wid in entry.get("osm_deck_ways", []):
        w = ways.get(wid)
        if w is None or not w.get("geometry"):
            raise KeyError(f"bridge {eid}: OSM deck way {wid} not in the raw file (re-run scripts/04p_fetch_bridges.py)")
        e_, n_ = to_local(np.array([p["lon"] for p in w["geometry"]], float),
                          np.array([p["lat"] for p in w["geometry"]], float))
        deck_lines.append(LineString(np.column_stack([e_, n_])))
        (_, half), = osm_bridge_lines([w])
        carriageways.append((deck_lines[-1], half, _lanes(w)))
    by_id = {t["id"]: t for t in tower_entries}
    towers = [by_id[i] for i in entry["tower_entries"]] if "tower_entries" in entry else list(tower_entries)
    ca, cb, legs = tower_axis(osm_elements, towers, to_local)
    span = float(np.linalg.norm(cb - ca))
    u = (cb - ca) / span
    v = np.array([-u[1], u[0]])
    h_a, h_b = float(towers[0]["height_m"]), float(towers[1]["height_m"])

    side = float(d["side_span_m"])
    anch_len = float(d.get("anchorage_length_m", 0.0))
    s_start, s_end = -side - anch_len, span + side + anch_len
    color = list(d["color"])

    # Deck top along s: the LiDAR profile where it has returns, else the
    # vertical curve through the clearance (+ deck thickness) at mid-span
    thick = float(d["deck_thickness_m"])
    curve = dict(s_mid=span / 2, z_mid=float(d["clearance_m"]) + thick, half_len=span / 2 + side,
                 end_grade=float(d["vertical_curve_end_grade"]))
    bins, prof = lidar_profile(lidar, ca, u, s_start, s_end, method["profile_bin_m"],
                               method["profile_half_width_m"], mhw_m)
    ok = np.isfinite(prof)

    def deck_top(s):
        s = np.atleast_1d(np.asarray(s, float))
        z = vertical_curve(s, **curve)
        if ok.any():
            # Within half a bin of the outermost measured bins the profile
            # holds its end value; past that the curve takes over
            lo, hi = bins[ok][0] - method["profile_bin_m"] / 2, bins[ok][-1] + method["profile_bin_m"] / 2
            inside = (s >= lo) & (s <= hi)
            z[inside] = np.interp(s[inside], bins[ok], prof[ok])
        return z

    buildings, tubes = [], []
    n = 0

    def add_box(part, ring, z0, h, rgb, roof=None):
        nonlocal n
        b = {"id": f"bridge-{eid}-{part}-{n}", "h": _r(h), "z0": _r(z0), "polys": [[ring]], "fixed_color": list(rgb)}
        if roof is not None:
            b["roof_rgb"] = list(roof)
        buildings.append(b)
        n += 1

    def add_tube(part, pts, r, rgb):
        nonlocal n
        tubes.append({"id": f"bridge-{eid}-{part}-{n}", "pts": [[_r(c) for c in p] for p in pts], "r": float(r),
                      "color": list(rgb)})
        n += 1

    def at(s, t=0.0):
        return ca + u * s + v * t

    # Deck: equal steps of ~segment_m, each at its center's height
    nseg = max(int(np.ceil((s_end - s_start) / method["segment_m"])), 1)
    edges = np.linspace(s_start, s_end, nseg + 1)
    mids = (edges[:-1] + edges[1:]) / 2
    tops = deck_top(mids)
    cx, cy = ca[0] + u[0] * mids, ca[1] + u[1] * mids
    wet = shapely.contains_xy(water, cx, cy) if water is not None and not water.is_empty else np.zeros(nseg, bool)
    # Which segments float on their deck thickness. Over water, all. Over
    # land, land_rule "anchorages" (default) floats the suspended spans too
    # and grounds only what lies past the anchorage front faces: the side
    # spans hang over open ground (the Ben Franklin over Columbus Blvd and
    # I-95, the Walt Whitman over Packer Ave and Gloucester City), and a
    # solid deck there drew 110-320 m walls 30-50 m tall. "all_land"
    # grounds every land segment (a solid viaduct)
    floats = wet.copy()
    if method["land_rule"] == "anchorages":
        floats |= (mids > -side) & (mids < span + side)
    elif method["land_rule"] != "all_land":
        raise ValueError(f"bridge {eid}: unknown land_rule {method['land_rule']!r}")
    half_w = float(d["deck_width_m"]) / 2
    for i in range(nseg):
        z0 = tops[i] - thick if floats[i] else 0.0
        add_box("deck", _rect(at(edges[i]), at(edges[i + 1]), v, half_w), z0, tops[i], color, d["deck_rgb"])

    def seg_of(s):
        return int(np.clip(np.searchsorted(edges, s, side="right") - 1, 0, nseg - 1))

    # Lane lines: solid edges, dashed lines between lanes. A dash crossing a
    # step is split so each piece sits on its own segment's top
    road = float(d["roadway_width_m"])
    lanes = int(d["lanes"])
    lw, lh = float(d["lane_line_width_m"]), float(d["lane_line_height_m"])
    dash, gap = float(d["dash_m"]), float(d["gap_m"])
    for k in (0, lanes):
        t = -road / 2 + k * road / lanes
        t += lw / 2 if k == 0 else -lw / 2
        for i in range(nseg):
            add_box("lane", _rect(at(edges[i], t), at(edges[i + 1], t), v, lw / 2), tops[i], tops[i] + lh, d["lane_rgb"])
    dashes = []
    s = s_start
    while s < s_end:
        dashes.append((s, min(s + dash, s_end)))
        s += dash + gap
    for k in range(1, lanes):
        t = -road / 2 + k * road / lanes
        for d0, d1 in dashes:
            i0, i1 = seg_of(d0), seg_of(d1 - 1e-9)
            for i in range(i0, i1 + 1):
                p0, p1 = max(d0, edges[i]), min(d1, edges[i + 1])
                if p1 - p0 > 0.05:
                    add_box("lane", _rect(at(p0, t), at(p1, t), v, lw / 2), tops[i], tops[i] + lh, d["lane_rgb"])

    # Cable (and truss) lines: through the paired legs' centers
    lines = {}
    for sgn in (1, -1):
        pa, pb = legs[0][sgn], legs[1][sgn]
        lines[sgn] = (pa, (pb - pa) / np.linalg.norm(pb - pa), float(np.linalg.norm(pb - pa)))
    t_truss = float(np.mean([abs((legs[i][sgn] - (ca, cb)[i]) @ v) for i in (0, 1) for sgn in (1, -1)]))

    # PATCO track beds outside the truss lines (Ben Franklin)
    if int(d.get("patco_tracks", 0)) >= 2:
        bed = float(d["patco_bed_width_m"])
        t0, t1 = t_truss + 1.0, min(t_truss + 1.0 + bed, half_w)
        for i in range(nseg):
            for sgn in (1, -1):
                add_box("patco", _rect_t(at(edges[i]), at(edges[i + 1]), v, sgn * t0, sgn * t1), tops[i],
                        tops[i] + 0.15, d["patco_rgb"], d["patco_rgb"])

    # Anchorage blocks: from the roadway edge out to the block's width on
    # each side, front face one side span outside the tower; the road runs
    # between them at deck level
    anchor_rise = float(d.get("cable_anchor_above_deck_m", 0.0))
    anchors = {}
    for end, s_front, s_back in (("a", -side, -side - anch_len), ("b", span + side, span + side + anch_len)):
        anchors[end] = s_front
        if anch_len > 0 and "anchorage_width_m" in d:
            top = float(deck_top(s_front)[0]) + float(d["anchorage_rise_m"])
            for sgn in (1, -1):
                add_box("anchorage", _rect_t(at(s_front), at(s_back), v, sgn * road / 2,
                                             sgn * float(d["anchorage_width_m"]) / 2), 0.0, top, color, color)

    # Main cables: anchorage -> tower A top -> parabola -> tower B top ->
    # anchorage. Side spans sag by main sag x (side/main)^2: the same
    # horizontal tension under the same load per meter
    sag = float(d["cable_sag_m"])
    side_sag = sag * (side / span) ** 2
    step = method["cable_step_m"]
    cable_z = {}
    for sgn, (pa, uc, lc) in lines.items():
        # Anchor heights: the deck top where the cable line's ends project
        # onto the tower line (the two lines are within a degree or so)
        za = float(deck_top((pa + uc * -side - ca) @ u)[0]) + anchor_rise
        zb = float(deck_top((pa + uc * (lc + side) - ca) @ u)[0]) + anchor_rise
        pieces = [(-side, za, 0.0, h_a, side_sag), (0.0, h_a, lc, h_b, sag), (lc, h_b, lc + side, zb, side_sag)]

        def zf(s, pieces=pieces):
            s = np.asarray(s, float)
            out = np.empty_like(s)
            for s0, z0, s1, z1, f in pieces:
                m = (s >= s0) & (s <= s1)
                out[m] = _parabola(s[m], s0, z0, s1, z1, f)
            return out

        cable_z[sgn] = zf
        ss = [np.linspace(s0, s1, max(int(np.ceil((s1 - s0) / step)), 1) + 1) for s0, _, s1, _, _ in pieces]
        ss = np.concatenate([ss[0], ss[1][1:], ss[2][1:]])
        pts = np.column_stack([pa[0] + uc[0] * ss, pa[1] + uc[1] * ss, zf(ss)])
        add_tube("cable", pts, d["cable_radius_m"], color)

    # Panel points: main span from the towers, side spans from the towers
    # outward, each spacing adjusted to divide its span evenly
    def panels(length, spacing):
        k = max(int(round(length / spacing)), 1)
        return np.linspace(0.0, length, k + 1)

    sp_main, sp_side = float(d["hanger_spacing_main_m"]), float(d["hanger_spacing_side_m"])
    hanger_r = float(d["hanger_radius_m"])
    for sgn, (pa, uc, lc) in lines.items():
        sp = np.concatenate([-panels(side, sp_side)[::-1], panels(lc, sp_main)[1:], lc + panels(side, sp_side)[1:]])
        interior = sp[(sp > -side + 1e-6) & (sp < lc + side - 1e-6) & (np.abs(sp) > 1e-6) & (np.abs(sp - lc) > 1e-6)]
        def s_deck(s, pa=pa, uc=uc):
            # A cable-line point's s on the tower line, for the deck height under it
            return (pa + uc * np.asarray(s, float)[..., None] - ca) @ u

        zc, zd = cable_z[sgn](interior), deck_top(s_deck(interior))
        for s, z_top, z_bot in zip(interior, zc, zd):
            if z_top - z_bot >= MIN_HANGER_M:
                p = pa + uc * s
                add_tube("hanger", [[p[0], p[1], z_bot], [p[0], p[1], z_top]], hanger_r, color)
        # Warren stiffening truss above the deck (Ben Franklin): chords at
        # the deck top and truss_depth above it, diagonals zig-zagging
        # between panel points
        if "truss_depth_m" in d:
            depth, tr = float(d["truss_depth_m"]), float(d["truss_radius_m"])
            xy = pa + uc * sp[:, None]
            bot = deck_top(s_deck(sp))
            add_tube("truss", np.column_stack([xy, bot]), tr, color)
            add_tube("truss", np.column_stack([xy, bot + depth]), tr, color)
            for i in range(sp.size - 1):
                lo, hi = (bot[i], bot[i + 1] + depth) if i % 2 == 0 else (bot[i] + depth, bot[i + 1])
                add_tube("truss", [[*xy[i], lo], [*xy[i + 1], hi]], tr, color)

    # Tower crossbeams: floating boxes from leg center to leg center,
    # strut_thickness_m along the bridge; X-bracing in each panel between
    # consecutive struts
    beams = sorted((float(b0), float(b1)) for b0, b1 in d.get("crossbeams_m", []))
    thick_s = float(d.get("strut_thickness_m", 3.0))
    for i in (0, 1):
        lm, lp = legs[i][-1], legs[i][1]
        w = (lp - lm) / np.linalg.norm(lp - lm)
        along = np.array([w[1], -w[0]])
        for b0, b1 in beams:
            ring = np.round(np.array([lm - along * thick_s / 2, lp - along * thick_s / 2,
                                      lp + along * thick_s / 2, lm + along * thick_s / 2]), 2).tolist()
            add_box("strut", ring, b0, b1, color, color)
        if d.get("x_bracing"):
            for (_, lo), (hi, _) in zip(beams, beams[1:]):
                add_tube("brace", [[*lm, lo], [*lp, hi]], d["brace_radius_m"], color)
                add_tube("brace", [[*lp, lo], [*lm, hi]], d["brace_radius_m"], color)

    # Approach spans past the anchorages, along the OSM deck ways
    approach_qa = None
    if entry.get("approach"):
        acfg = _values(method.get("approach") or {})
        if "approach_fallback_grade" in d:
            acfg["fallback_grade"] = float(d["approach_fallback_grade"])
        look = {"wall_rgb": color, "deck_rgb": d["deck_rgb"], "lane_rgb": d["lane_rgb"], "lw": lw, "lh": lh,
                "dash": dash, "gap": gap}
        approach_qa = {}
        for end, s_from, sign in (("a", s_start, -1.0), ("b", s_end, 1.0)):
            parts, approach_qa[end] = approach_decks(
                carriageways, ca, u, s_from, sign, float(deck_top(s_from)[0]), 2 * half_w, lidar, ground, mhw_m,
                acfg, method["segment_m"], method["profile_half_width_m"], look)
            for part, ring, z0, h, rgb, roof in parts:
                add_box(part, ring, z0, h, rgb, roof)

    qa = {"tower_centers": [np.round(ca, 1).tolist(), np.round(cb, 1).tolist()], "tower_distance_m": round(span, 1),
          "anchorages": [np.round(at(anchors["a"]), 1).tolist(), np.round(at(anchors["b"]), 1).tolist()],
          "deck_m": [round(s_start, 1), round(s_end, 1)], "segments": nseg, "over_water": int(wet.sum()), "floating": int(floats.sum()),
          "deck_top_m": [round(float(tops.min()), 2), round(float(tops.max()), 2)],
          "lidar_bins": int(ok.sum()), "bins": int(bins.size),
          "profile": [(round(float(s), 1), None if not np.isfinite(z) else round(float(z), 2),
                       round(float(vertical_curve(s, **curve)), 2)) for s, z in zip(bins, prof)],
          "osm_midline_offset_m": _osm_midline_offset(deck_lines, ca, u, s_start, s_end),
          "cable_half_spacing_m": round(t_truss, 2)}
    if approach_qa is not None:
        qa["approach"] = approach_qa
    return {"buildings": buildings, "tubes": tubes, "qa": qa}


def npz_window(path, key: str, bounds_local, res: float = 0.5):
    """{"dsm": window, "origin": (west, north), "res"} of one array of an
    area's LiDAR grid (data/processed/<area>_lidar_grid.npz) over
    bounds_local (minx, miny, maxx, maxy), or None when the bounds miss the
    grid. The grids are ~1.2 GB per array, compressed; this streams the
    array's rows out of the zip and keeps only the window, so a bridge needs
    a few MB instead of the whole array in memory."""
    import zipfile

    with np.load(path) as z:
        origin = tuple(float(x) for x in z["origin"])
    west, north = origin
    minx, miny, maxx, maxy = bounds_local
    with zipfile.ZipFile(path) as zf, zf.open(f"{key}.npy") as f:
        version = np.lib.format.read_magic(f)
        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        (H, W), fortran, dtype = reader(f)
        if fortran:
            raise ValueError(f"{path}:{key} is Fortran-ordered; the row reader needs C order")
        c0, c1 = max(int(np.floor((minx - west) / res)), 0), min(int(np.ceil((maxx - west) / res)), W)
        r0, r1 = max(int(np.floor((north - maxy) / res)), 0), min(int(np.ceil((north - miny) / res)), H)
        if c1 <= c0 or r1 <= r0:
            return None
        row_bytes = W * dtype.itemsize
        skip = r0
        while skip:  # zip members can't seek; read past the rows above the window
            k = min(skip, 2000)
            f.read(k * row_bytes)
            skip -= k
        rows = np.frombuffer(f.read((r1 - r0) * row_bytes), dtype=dtype).reshape(r1 - r0, W)
        win = rows[:, c0:c1].copy()
    return {key: win, "dsm": win, "origin": (west + c0 * res, north - r0 * res), "res": res}


def suspension_structures_for(cfg, frame) -> dict:
    """suspension_structure for each of the area's entries in
    config/bridge_structures.json: {"buildings", "tubes", "qa": {entry id:
    ...}}; {"buildings": [], "tubes": []} unless the area config has
    "bridge_structures": true. Towers from config/bridge_towers.json and
    data/raw/<area>_bridge_towers.json (04q), deck ways from
    data/raw/<area>_bridges.json (04p), water from water_local, deck heights
    from data/processed/<area>_lidar_grid.npz (the vertical curve alone when
    the grid is missing)."""
    if not cfg.get("bridge_structures"):
        return {"buildings": [], "tubes": []}
    from .lidar import RES_M
    from .projection import REPO_ROOT
    from .sources import RAW

    conf = json.loads((REPO_ROOT / "config" / BRIDGE_STRUCTURES).read_text())
    entries = [e for e in conf["entries"] if e.get("area") == cfg["name"]]
    if not entries:
        return {"buildings": [], "tubes": []}
    towers = json.loads((REPO_ROOT / "config" / BRIDGE_TOWERS).read_text())["entries"]
    elements = json.loads((RAW / f"{cfg['name']}_bridge_towers.json").read_text())["elements"]
    deck_file = RAW / f"{cfg['name']}_bridges.json"
    if deck_file.exists():
        elements = elements + json.loads(deck_file.read_text())["elements"]
    water = water_local(cfg, frame)
    mhw = float(conf["datum"]["mhw_navd88_m"]["value"])
    method = dict(conf.get("method", {}))
    grid = REPO_ROOT / "data" / "processed" / f"{cfg['name']}_lidar_grid.npz"
    out = {"buildings": [], "tubes": [], "qa": {}}
    for entry in entries:
        tower_entries = [t for t in towers if t["id"] in entry["tower_entries"]]
        lidar = ground = None
        if grid.exists():
            ca, cb, _ = tower_axis(elements, [next(t for t in towers if t["id"] == i) for i in entry["tower_entries"]],
                                   frame.to_local)
            u = (cb - ca) / np.linalg.norm(cb - ca)
            reach = float(entry["dims"]["side_span_m"]["value"]) + \
                float(entry["dims"].get("anchorage_length_m", {"value": 0.0})["value"]) + method.get("lidar_window_pad_m", 60.0)
            pts = [ca - u * reach, cb + u * reach]
            pad = method.get("lidar_window_pad_m", 60.0)
            if entry.get("approach"):
                # The approaches follow the OSM deck ways out to ~1.5 km, and
                # their local ground is sampled ground_radius_m around them
                pad += float(_values(method.get("approach") or {}).get("ground_radius_m", 0.0))
                for e in elements:
                    if e.get("id") in entry.get("osm_deck_ways", []) and e.get("geometry"):
                        pts += list(np.column_stack(frame.to_local(np.array([q["lon"] for q in e["geometry"]], float),
                                                                   np.array([q["lat"] for q in e["geometry"]], float))))
            pts = np.asarray(pts)
            bounds = (pts[:, 0].min() - pad, pts[:, 1].min() - pad, pts[:, 0].max() + pad, pts[:, 1].max() + pad)
            lidar = npz_window(grid, "dsm", bounds, RES_M)
            if entry.get("approach"):
                ground = npz_window(grid, "ground", bounds, RES_M)
        got = suspension_structure(entry, elements, tower_entries, frame.to_local, water=water, lidar=lidar, mhw_m=mhw,
                                   method=method, ground=ground)
        out["buildings"] += got["buildings"]
        out["tubes"] += got["tubes"]
        out["qa"][entry["id"]] = got["qa"]
    return out


# --- Ground under the raised decks (Nov. 9) ---
# The 2024 aerial on the ground plane still shows each deck where it is in
# plan, flat at y = 0. With the modeled deck raised 30-50 m, that photo deck
# shows on screen as a second, ghost road below and beside the real one.
# It is painted out of the ground texture: over water with the river around
# it, over land with the ground around it (a smooth fill from the hole's
# edges, _fill_from; OpenCV's Telea inpaint is not in this environment, and
# the model redraws the surface anyway).
DECK_PLAN_PARTS = ("deck", "approach")


def _part_of(bid) -> str:
    """Part name of a structure id "bridge-<entry>-<part>-<n>" (entry ids
    use underscores, never hyphens), or of a tower leg "tower-..."."""
    bits = str(bid).split("-")
    if bits[0] == "tower":
        return "leg"
    return bits[2] if len(bits) >= 4 else ""


def deck_plan(buildings, margin_m: float = 5.0):
    """Local-m plan footprint of a structure's deck and approach segments
    (not lane lines, anchorages, piers or struts), grown margin_m."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polys = [Polygon(b["polys"][0][0]) for b in buildings if _part_of(b["id"]) in DECK_PLAN_PARTS]
    if not polys:
        return Polygon()
    return unary_union([p.buffer(0) for p in polys]).buffer(margin_m, join_style=2)


def paint_out_decks(rgb: np.ndarray, hole: np.ndarray, water: np.ndarray) -> np.ndarray:
    """rgb with `hole` filled: its water pixels from the water around it,
    its land pixels from the land around it (smooth fields, _fill_from), so
    river color never bleeds onto land or the reverse. Pixels outside the
    hole are unchanged."""
    rgb = np.asarray(rgb)
    out = rgb.copy()
    for sel, src, is_water in ((hole & water, water & ~hole, True), (hole & ~water, ~water & ~hole, False)):
        if not sel.any():
            continue
        if not src.any():
            src = ~hole  # a hole with only the other kind around it
        if not src.any():
            continue
        if is_water:
            # Only river-colored pixels feed the river fill: the photo deck's
            # lit railing and leftover blue-gray shadow next to the hole
            # (both on mapped water) streaked it in the Nov. 9 test render
            med = np.median(rgb[..., :3][src], axis=0).astype(np.int16)
            ok = src & (np.abs(rgb[..., :3].astype(np.int16) - med).max(axis=2) <= SHADOW_SOURCE_TOL)
            src = ok if ok.any() else src
        filled = _fill_from(rgb[..., :3], src, sel)
        out[..., :3][sel] = np.clip(np.round(filled[sel]), 0, 255).astype(np.uint8)
    return out


# --- Repaint protection for the modeled structures (Nov. 9) ---
# The bridge band (band_geometry: a deck swept -25..+12 m) and the hard deck
# mask (deck_screen, at y = 0) assume a deck at water level. With the Ben
# Franklin and Walt Whitman modeled in 3D, both are wrong there: the deck is
# 30-50 m up, with cables to 116 m. Their lines are clipped out of the band
# and deck inputs (structure_corridor), and a protection region from the
# modeled structure takes over (structure_zones): its solid parts are never
# repainted, its cables and hanger zone only where the drawing drew river.
STRUCTURE_CORRIDOR_PAD_M = 10.0  # past the deck edge: walkways, PATCO and the City centerline's drift
CABLE_PROTECT_PX = 10.0  # main cables, each side of the screen line
MEMBER_PROTECT_PX = 4.0  # hangers, truss members and X-bracing
HANGER_LINK_M = 25.0  # hangers this close in plan bound one hanger-zone quad (panels 6.25 m; 2 at a tower)
LINE_PARTS = ("lane", "approach_lane", "patco")  # thin parts lying on the deck: inside its sweep


def structure_corridor(entries, elements, to_local, pad_m: float = STRUCTURE_CORRIDOR_PAD_M):
    """Local-m corridor of the modeled bridges: each entry's OSM deck ways
    buffered by half its deck width plus pad_m. Raises KeyError for a
    missing way, like suspension_structure."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    ways = {e.get("id"): e for e in elements if e.get("type", "way") == "way"}
    out = []
    for entry in entries:
        half = float(entry["dims"]["deck_width_m"]["value"]) / 2 + pad_m
        for wid in entry.get("osm_deck_ways", []):
            w = ways.get(wid)
            if w is None or not w.get("geometry"):
                raise KeyError(f"bridge {entry['id']}: OSM deck way {wid} not in the raw file")
            e_, n_ = to_local(np.array([p["lon"] for p in w["geometry"]], float),
                              np.array([p["lat"] for p in w["geometry"]], float))
            out.append(LineString(np.column_stack([e_, n_])).buffer(half))
    return unary_union(out) if out else Polygon()


def clip_lines(lines, corridor):
    """[(line, half width)] with the parts inside `corridor` removed."""
    if corridor is None or corridor.is_empty:
        return list(lines)
    out = []
    for ln, half in lines:
        rest = ln.difference(corridor)
        if not rest.is_empty:
            out.append((rest, half))
    return out


def _structure_entries(cfg):
    from .projection import REPO_ROOT

    conf = json.loads((REPO_ROOT / "config" / BRIDGE_STRUCTURES).read_text())
    return [e for e in conf["entries"] if e.get("area") == cfg["name"]]


def structure_corridor_for(cfg, frame):
    """structure_corridor of the area's config/bridge_structures.json
    entries; empty unless the area config has "bridge_structures": true."""
    from shapely.geometry import Polygon

    from .sources import RAW

    if not cfg.get("bridge_structures"):
        return Polygon()
    entries = _structure_entries(cfg)
    if not entries:
        return Polygon()
    elements = json.loads((RAW / f"{cfg['name']}_bridges.json").read_text())["elements"]
    return structure_corridor(entries, elements, frame.to_local)


def structure_zones(buildings, tubes, legs, cam, x_origin: float, y_origin: float,
                    cable_px: float = CABLE_PROTECT_PX, member_px: float = MEMBER_PROTECT_PX):
    """(solid, members): the screen (mosaic px) regions the modeled structure
    covers. solid: each prism (deck and approach segments, piers, anchorages,
    crossbeams, tower legs) swept from z0 to h; never repainted. members:
    each main cable's screen line buffered cable_px, the hanger zone (quads
    between consecutive hangers, cable down to deck) and other members
    buffered member_px, less solid. Most of the members zone is open river
    seen between thin tubes, which the model draws in its raw river colors
    (Nov. 9 review: a tan band between each cable and the deck on the BFB
    and WWB), so the repaint takes river-colored pixels there and keeps the
    drawn strokes (refine_members)."""
    from shapely.affinity import translate
    from shapely.geometry import LineString, MultiPoint, Polygon
    from shapely.ops import unary_union

    def scr(e, n, z):
        x, y = cam.world_to_screen(np.asarray(e, float), np.asarray(n, float), np.asarray(z, float))
        return np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])

    solid, thin = [], []
    for b in list(buildings) + list(legs):
        if _part_of(b["id"]) in LINE_PARTS:
            continue
        ring = np.asarray(b["polys"][0][0], float)
        z0 = float(b.get("z0") or 0.0)
        pts = np.vstack([scr(ring[:, 0], ring[:, 1], np.full(len(ring), z0)),
                         scr(ring[:, 0], ring[:, 1], np.full(len(ring), float(b["h"])))])
        solid.append(MultiPoint(pts).convex_hull)
    prev = None
    for t in tubes:
        part = _part_of(t["id"])
        p = np.asarray(t["pts"], float)
        sp = scr(p[:, 0], p[:, 1], p[:, 2])
        if part == "hanger":
            if prev is not None and np.hypot(*(p[0, :2] - prev[0][0, :2])) <= HANGER_LINK_M:
                thin.append(MultiPoint(np.vstack([sp, prev[1]])).convex_hull)
            prev = (p, sp)
        thin.append(LineString(sp).buffer(cable_px if part == "cable" else member_px))
    s = unary_union(solid) if solid else Polygon()
    m = unary_union(thin).difference(s) if thin else Polygon()
    return translate(s, -x_origin, -y_origin), translate(m, -x_origin, -y_origin)


def structure_protect(buildings, tubes, legs, cam, x_origin: float, y_origin: float,
                      cable_px: float = CABLE_PROTECT_PX, member_px: float = MEMBER_PROTECT_PX):
    """Whole screen region of the modeled structure (structure_zones' solid
    and members together), for checks that treat the bridge as one object
    (invented-water scan, the single-mosaic repaint). Tighter than one sweep
    from the water to the tower tops: the river seen below the deck and past
    the cables stays the repaint's."""
    from shapely.ops import unary_union

    return unary_union(structure_zones(buildings, tubes, legs, cam, x_origin, y_origin, cable_px, member_px))


_STRUCTURES = {}


def suspension_structures_cached(cfg, frame) -> dict:
    """suspension_structures_for, computed once per area per process (it
    streams LiDAR windows for each bridge)."""
    if cfg["name"] not in _STRUCTURES:
        _STRUCTURES[cfg["name"]] = suspension_structures_for(cfg, frame)
    return _STRUCTURES[cfg["name"]]


def structure_zones_for(cfg, frame, cam, x_origin: float, y_origin: float):
    """structure_zones (solid, members) of the area's modeled bridges and
    their tower legs (config/bridge_towers.json), mosaic px; both empty
    unless the area config has "bridge_structures": true."""
    from shapely.geometry import Polygon

    if not cfg.get("bridge_structures"):
        return Polygon(), Polygon()
    st = suspension_structures_cached(cfg, frame)
    if not st["buildings"] and not st["tubes"]:
        return Polygon(), Polygon()
    towers = {t for e in _structure_entries(cfg) for t in e["tower_entries"]}
    legs = [b for b in tower_legs_for(cfg, frame) if b["id"].rsplit("-", 1)[0][len("tower-"):] in towers]
    return structure_zones(st["buildings"], st["tubes"], legs, cam, x_origin, y_origin)


def structure_protect_for(cfg, frame, cam, x_origin: float, y_origin: float):
    """structure_protect of the area's modeled bridges: both zones of
    structure_zones_for as one region."""
    from shapely.ops import unary_union

    return unary_union(structure_zones_for(cfg, frame, cam, x_origin, y_origin))
