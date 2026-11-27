"""Front slopes on postwar rowhouses (docs/building_age_plan.md, Phase B).

Many Philadelphia rows built after World War II (OPA "ROW POST WAR",
"TWIN POST WAR") have a short shingled slope along the top of the front
wall: a pent or mansard-style strip in front of a flat roof. The map drew
every roof as a flat prism, so these houses lost the one roof feature a
viewer sees from the street.

The LiDAR can't resolve a strip under a meter deep on one house, but it
shows it on average: front-to-back roof profiles of 3,852 Mayfair postwar
rows (scripts/46_roof_front_profiles.py, output/building_age/
roof_front_profiles.json) have a median 0.5 m below the roof 0.5 m from the
front, 0.09 m below at 0.75 m, and level from 1 m back. Bins nearer the
front than 0.5 m are empty (the 0.5 m grid's edge cells mix in the ground),
so the drop at the wall itself is an extrapolation. FRONT_SLOPE_* below are
set from that profile.

Geometry. A slope that sat under the flat roof would be hidden by it, so the
footprint is cut in two: the main block keeps its height, and a strip
FRONT_SLOPE_DEPTH_M deep along the street wall drops to h - DROP. The slope
runs from the strip's wall top (plus a small overhang past the wall) up to
the main block's roof edge. Both pieces stay ordinary prisms in the scene;
only the slope triangles are new ("roof_facets"), and the alignment check
projects them the same way (scripts/09_check_alignment.py).

Shingle colors are an assumption, not from a source: muted gray and
gray-brown asphalt tones, chosen to read as a roof against brick. The
blind review (Phase D) judges them.
"""

from __future__ import annotations

import zlib

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

FRONT_SLOPE_DEPTH_M = 0.75  # level by 0.75-1.0 m from the front in the Mayfair profile
FRONT_SLOPE_DROP_M = 0.6  # 0.5 m low at 0.5 m back, extrapolated to the wall
FRONT_SLOPE_OVERHANG_M = 0.15  # eave past the wall: a shadow line under the slope
MIN_EDGE_M = 3.0  # narrower street walls (a corner sliver, a garage) get no slope
MAX_H_M = 20.0  # rows and twins only; nothing tall
MIN_STRIP_H_M = 2.5  # the strip must leave a real wall below it
MAX_ANGLE_DEG = 25.0  # a wall faces the street when its normal is this close to the street direction
OUTSIDE_M = 1.0  # the cut reaches this far past the street wall, to catch a LiDAR outline's stair steps
FRONT_JOG_M = 0.6  # a step in the front wall up to this deep (a vestibule, a shallow bay) still counts as one wall
PART_REACH_M = 1.5  # a LiDAR part must come within this of the street wall to get the slope
ODD_FRONT_TOL = 0.35  # the strip's area may differ from wall length x depth by this share (jogs, stair steps)
SHINGLE_PALETTE = [(92, 90, 88), (108, 102, 96), (84, 78, 74), (118, 112, 104), (96, 86, 78)]
SHINGLE_JITTER = 6


def _outer(poly, tol=0.05):
    """The largest polygon, counter-clockwise, simplified at `tol` m."""
    if poly.geom_type != "Polygon":
        poly = max(getattr(poly, "geoms", []), key=lambda g: g.area)
    return orient(Polygon(poly.exterior).simplify(tol), 1.0)


def front_edge(poly, direction):
    """The longest wall edge ((e0, n0), (e1, n1)) whose outward normal is
    within MAX_ANGLE_DEG of `direction` (a street-facing unit normal from
    facades.front_dirs), or None. The outline is simplified at FRONT_JOG_M
    first: many Mayfair row outlines step about 0.5 m across the front (a
    vestibule or bay), which otherwise splits a 5 m front into 2-3 m pieces."""
    p = _outer(poly, FRONT_JOG_M)
    dx0, dy0 = direction
    norm = (dx0 * dx0 + dy0 * dy0) ** 0.5 or 1.0
    dx0, dy0 = dx0 / norm, dy0 / norm
    cos_max = np.cos(np.radians(MAX_ANGLE_DEG))
    best, best_len = None, 0.0
    pts = list(p.exterior.coords)
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        length = (dx * dx + dy * dy) ** 0.5
        if length <= best_len or length < 1e-6:
            continue
        nx, ny = dy / length, -dx / length  # outward for a counter-clockwise ring
        if nx * dx0 + ny * dy0 < cos_max:
            continue
        best, best_len = ((x0, y0), (x1, y1)), length
    return best


def shingle_color(key):
    """A stable shingle color for one building (key: its id)."""
    h = zlib.crc32(str(key).encode())
    base = SHINGLE_PALETTE[h % len(SHINGLE_PALETTE)]
    j = ((h >> 8) % (2 * SHINGLE_JITTER + 1)) - SHINGLE_JITTER
    return [int(min(255, max(0, c + j))) for c in base]


def front_slope(poly, h, direction, key, outer=None, reasons=None):
    """Cut a footprint into a full-height main block and a lower front strip
    with a slope over it. Returns {"main", "strip": Polygon, "strip_h": m,
    "facets": [[[e, n, z] x 3], [...]], "color": [r, g, b]}, or None when the
    building doesn't qualify (too tall or low, no street wall MIN_EDGE_M
    long, or a shape the cut would mangle). With `reasons` (a Counter), each
    refusal is counted by reason for the scene's QA."""
    def refuse(why):
        if reasons is not None:
            reasons[why] += 1
        return None

    if not (MIN_STRIP_H_M + FRONT_SLOPE_DROP_M <= h <= MAX_H_M):
        return refuse("height")
    # The street wall is found on the City footprint (`outer`), not on a
    # LiDAR part: parts are traced on the 0.5 m grid, so on a diagonal street
    # their front is a staircase with no long straight edge
    edge = front_edge(outer if outer is not None else poly, direction)
    if edge is None:
        return refuse("no_street_wall")
    (x0, y0), (x1, y1) = edge
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    nx, ny = uy, -ux  # outward (street side)
    # A part covers only its own stretch of the wall (a twin's two halves are
    # one footprint in some records, but LiDAR parts split by height)
    t = [(x - x0) * ux + (y - y0) * uy for x, y in _outer(poly).exterior.coords]
    t0, t1 = max(0.0, min(t)), min(length, max(t))
    if outer is not None:
        # LiDAR parts are also inset at the sides; one that comes within 1 m
        # of the wall's end covers it (else a row of slopes would have gaps)
        t0 = 0.0 if t0 < 1.0 else t0
        t1 = length if t1 > length - 1.0 else t1
    if t1 - t0 < MIN_EDGE_M:
        return refuse("short_wall")
    full = length
    x0, y0, x1, y1 = x0 + ux * t0, y0 + uy * t0, x0 + ux * t1, y0 + uy * t1
    length = t1 - t0
    d = FRONT_SLOPE_DEPTH_M
    # The cutting rectangle runs OUTSIDE_M past the wall (a LiDAR outline's
    # steps can poke out past the City line; left in the main block they'd
    # stand full height in front of the slope) and a little past the edge's
    # ends, so a wall meeting its neighbors at a slight angle is cut cleanly
    # Ends: past the wall's end (where a LiDAR part's stair steps can poke
    # out sideways), but flush where a LiDAR part stops partway along the
    # wall, since its neighbor part gets its own strip there
    e0 = 0.5 if t0 == 0.0 else 0.0
    e1 = 0.5 if t1 == full else 0.0
    a = (x0 - ux * e0 + nx * OUTSIDE_M, y0 - uy * e0 + ny * OUTSIDE_M)
    b = (x1 + ux * e1 + nx * OUTSIDE_M, y1 + uy * e1 + ny * OUTSIDE_M)
    cut = Polygon([a, b, (x1 + ux * e1 - nx * d, y1 + uy * e1 - ny * d),
                   (x0 - ux * e0 - nx * d, y0 - uy * e0 - ny * d)])
    if outer is None:
        strip = poly.intersection(cut)
        if strip.is_empty or strip.area < 0.25 * length * d:
            return refuse("not_at_front")
    else:
        # A LiDAR part often stops short of the street wall: the traced roof
        # leaves out the lower front band, the slope itself. The strip comes
        # from the City outline, for parts that reach within PART_REACH_M of
        # the wall (not a rear ell or a higher back block)
        reach = Polygon([(x0 + nx * OUTSIDE_M, y0 + ny * OUTSIDE_M), (x1 + nx * OUTSIDE_M, y1 + ny * OUTSIDE_M),
                         (x1 - nx * PART_REACH_M, y1 - ny * PART_REACH_M),
                         (x0 - nx * PART_REACH_M, y0 - ny * PART_REACH_M)])
        if poly.intersection(reach).area < 0.25 * length * d:
            return refuse("not_at_front")
        strip = outer.intersection(cut)
    main = poly.difference(cut)
    # A stair-stepped LiDAR outline can leave the strip or the main block in
    # a few pieces; a scene part may hold several polygons, so that's fine
    # unless the main block is gone or mostly crumbs
    if main.is_empty:
        return refuse("cut_splits")
    pieces = [main] if main.geom_type == "Polygon" else list(main.geoms)
    if max(g.area for g in pieces) < 0.9 * main.area:
        return refuse("cut_splits")
    if strip.geom_type != "Polygon":
        strip = max(strip.geoms, key=lambda g: g.area) if hasattr(strip, "geoms") else strip
    # Rows are near-rectangles; a deep bay or a bite out of the front would
    # leave the slope hanging over air or under the roof. ODD_FRONT_TOL
    # allows the 0.5 m front steps and a LiDAR outline's stair steps
    if strip.is_empty or abs(strip.area - length * d) > ODD_FRONT_TOL * length * d:
        return refuse("odd_front")
    if main.area < 0.5 * poly.area:
        return refuse("small_part")
    drop, over = FRONT_SLOPE_DROP_M, FRONT_SLOPE_OVERHANG_M
    z_out = h - drop - over * drop / d
    p_out0 = [x0 + nx * over, y0 + ny * over, z_out]
    p_out1 = [x1 + nx * over, y1 + ny * over, z_out]
    p_in1 = [x1 - nx * d, y1 - ny * d, h]
    p_in0 = [x0 - nx * d, y0 - ny * d, h]
    facets = []
    for tri in ((p_out0, p_out1, p_in1), (p_out0, p_in1, p_in0)):
        nrm = np.cross(np.subtract(tri[1], tri[0]), np.subtract(tri[2], tri[0]))
        facets.append([list(map(float, p)) for p in (tri if nrm[2] > 0 else tri[::-1])])
    return {"main": main, "strip": strip, "strip_h": h - drop, "facets": facets, "color": shingle_color(key)}


def to_polys(poly):
    """Shapely polygon -> the scene's polys ([[exterior, *holes]], open
    rings, 0.01 m), as lidar.building_parts writes them."""
    def ring(r):
        return np.round(np.asarray(r.coords)[:-1], 2).tolist()

    geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    return [[ring(g.exterior), *[ring(i) for i in g.interiors]] for g in geoms]


def facet_record(fs):
    """The scene entry for one slope: {"t": triangles, "c": color}, 0.01 m."""
    return {"t": [[[round(v, 2) for v in p] for p in tri] for tri in fs["facets"]], "c": fs["color"]}


# --- Roof pitch from the LiDAR (moved from scripts/45_roof_forms.py) --------
#
# The 2022 LiDAR's 0.5 m surface grid (data/processed/<area>_lidar_grid.npz,
# "dsm" = highest return per cell, "ground" = ground surface). A plane is fit
# to every 5 x 5 cell (2.5 m) patch over the footprint shrunk by EDGE_M.
# Patches that fit a plane well (rms under PLANE_RESID_M) are "flat" (under
# FLAT_DEG) or "sloped" (STEEP_DEG to MAX_DEG); patches that don't fit are
# steps between roof levels, parapets, party walls or HVAC units and are left
# out (counting steep cells directly made rows with rear ells look half
# pitched). steep_share = sloped / (sloped + flat). Thresholds were first
# guesses checked by eye on sample sheets (docs/building_age_styles.md,
# section 4); scripts/45_roof_forms.py measures every footprint with them.

PITCH_RES_M = 0.5
EDGE_M = 0.6  # shrink footprints by this before measuring pitch (wall drop, misregistration)
MIN_CELLS = 12  # 3 m² of measurable roof
STEEP_DEG = 15.0  # a 15° slope is about 3.2:12; built-up flat roofs slope ~1°
FLAT_DEG = 8.0
MAX_DEG = 60.0
PLANE_RESID_M = 0.2
MIN_PLANAR = 8
PITCHED_SHARE = 0.55
FLAT_SHARE = 0.25
MIN_HEIGHT_M = 2.0  # roofs lower than this above ground aren't measured (sheds, LiDAR gaps)


def plane_fit(win, k=5, res=PITCH_RES_M):
    """(slope degrees, rms residual m) of a least-squares plane on each k x k
    patch, centered; edges padded by reflection."""
    from numpy.lib.stride_tricks import sliding_window_view

    r = k // 2
    pad = np.pad(win, r, mode="reflect")
    w = sliding_window_view(pad, (k, k))
    off = (np.arange(k) - r) * res
    yy, xx = np.meshgrid(off, off, indexing="ij")
    sxx = (xx ** 2).sum()
    zm = w.mean(axis=(-1, -2))
    a = (w * xx).sum(axis=(-1, -2)) / sxx
    b = (w * yy).sum(axis=(-1, -2)) / sxx
    resid = np.sqrt(((w - zm[..., None, None] - a[..., None, None] * xx - b[..., None, None] * yy) ** 2)
                    .mean(axis=(-1, -2)))
    return np.degrees(np.arctan(np.hypot(a, b))), resid


def roof_window(fp, dsm, ground, origin, res=PITCH_RES_M, pad=2):
    """The grid window around a footprint (local-m polygon): {"win" (surface,
    NaNs filled with the window median), "gnd", "tf" (rasterio transform),
    "c0", "r0"}, or None when it's outside the grid or mostly empty. `pad`
    cells of margin on each side."""
    from rasterio.transform import Affine

    minx, miny, maxx, maxy = fp.bounds
    c0 = int((minx - origin[0]) / res) - pad
    c1 = int((maxx - origin[0]) / res) + pad + 1
    r0 = int((origin[1] - maxy) / res) - pad
    r1 = int((origin[1] - miny) / res) + pad + 1
    if c0 < 0 or r0 < 0 or c1 > dsm.shape[1] or r1 > dsm.shape[0]:
        return None
    win = dsm[r0:r1, c0:c1].astype(np.float64)
    gnd = ground[r0:r1, c0:c1].astype(np.float64)
    if np.isnan(win).mean() > 0.5:
        return None
    win = np.where(np.isnan(win), np.nanmedian(win), win)
    tf = Affine(res, 0, origin[0] + c0 * res, 0, -res, origin[1] - r0 * res)
    return {"win": win, "gnd": gnd, "tf": tf, "c0": c0, "r0": r0}


def roof_pitch(fp, dsm, ground, origin, res=PITCH_RES_M, window=None):
    """Pitch class of one footprint's roof: {"cls": pitched | flat | mixed |
    unclear | too_small | low, plus "cells", "planar_share", "roof_h_m",
    "steep_share" when measured}, or None outside the grid."""
    from rasterio.features import geometry_mask

    w = window or roof_window(fp, dsm, ground, origin, res)
    if w is None:
        return None
    win, gnd, tf = w["win"], w["gnd"], w["tf"]
    inner = fp.buffer(-EDGE_M)
    if inner.is_empty:
        return {"cls": "too_small"}
    m = geometry_mask([inner], out_shape=win.shape, transform=tf, invert=True)
    if m.sum() < MIN_CELLS:
        return {"cls": "too_small"}
    h = win - np.nan_to_num(gnd, nan=float(np.nanmedian(gnd)) if not np.isnan(gnd).all() else 0.0)
    if np.median(h[m]) < MIN_HEIGHT_M:
        return {"cls": "low"}
    pdeg, resid = plane_fit(win, res=res)
    planar = m & (resid < PLANE_RESID_M)
    sloped = planar & (pdeg >= STEEP_DEG) & (pdeg <= MAX_DEG)
    flat = planar & (pdeg < FLAT_DEG)
    n_pl = int(sloped.sum() + flat.sum())
    steep = float(sloped.sum() / n_pl) if n_pl else 0.0
    if n_pl < MIN_PLANAR:
        cls = "unclear"
    else:
        cls = "pitched" if steep >= PITCHED_SHARE else "flat" if steep <= FLAT_SHARE else "mixed"
    return {"cells": int(m.sum()), "planar_share": round(n_pl / int(m.sum()), 3),
            "roof_h_m": round(float(np.median(h[m])), 2), "steep_share": round(steep, 3), "cls": cls}


# --- Gables and hips fitted to the LiDAR (docs/building_age_plan.md, Phase C)
#
# The map drew every roof as flat tiers (lidar.building_parts puts tiers at
# least 2 m apart), so the 64,131 pitched roofs the LiDAR sees (section 4 of
# docs/building_age_styles.md) came out as stepped boxes. For a simple
# footprint (nearly its minimum rotated rectangle) with a pitched roof, each
# model is a set of the rectangle's sides that are eaves, and the roof is
# z = eave + k * (distance to the nearest of those sides): the two long sides
# (a gable, ridge along the house), the two short ends (a gable across it),
# all four (a hip), three (one half of a twin under a hip over the pair; the
# fourth side is the party wall) or one (a single slope: a twin half whose
# pair's ridge is the party wall, a shed or lean-to). A model is kept when most of the
# roof lies within FIT_TOL_M of it, its pitch is plausible, and it beats a
# flat roof clearly; otherwise the building keeps its tiers. Robust refits
# drop chimneys, dormers and branches over the roof; a roof mostly under
# trees doesn't fit any plane and is refused.

SIMPLE_MIN = 0.85  # footprint area / minimum rotated rectangle area
FIT_TOL_M = 0.35  # a cell fits a model within this
# Share of roof cells that must fit. Set from a sheet of LiDAR surfaces next
# to their fitted models on the Northeast pilot spot (Nov. 23, 2026): fits
# from about 0.7 up matched the roofs by eye (trees at an edge, a dormer or a
# chimney cost the rest); below that, wrong forms (a gable laid over an odd
# lower surface) became common. Of 324 roofs the pitch test calls pitched
# there, 102 fit at 0.7; the rest are compound roofs (T and L gables, porch
# roofs) or footprints that aren't simple, which keep their tiers
MIN_FIT_SHARE = 0.7
MIN_GAIN = 0.25  # the model must fit this much more of the roof than a flat roof does
PITCH_RANGE_DEG = (15.0, 55.0)  # 3.2:12 to about 17:12
MIN_EAVE_M = 2.0
MAX_RIDGE_M = 25.0  # houses, churches' naves are out of scope
# Eave sides of the rectangle: s+/s- are the short ends (u = +/-), t+/t- the
# long sides. Order is the preference on near-ties: simpler forms first
ROOF_MODELS = [
    ("gable", ("t+", "t-")), ("gable_cross", ("s+", "s-")), ("hip", ("s+", "s-", "t+", "t-")),
    ("half_hip", ("s-", "t+", "t-")), ("half_hip", ("s+", "t+", "t-")),
    ("half_hip", ("s+", "s-", "t-")), ("half_hip", ("s+", "s-", "t+")),
    ("shed", ("t+",)), ("shed", ("t-",)), ("shed", ("s+",)), ("shed", ("s-",)),
]
TIE_SHARE = 0.02  # a later (less simple) model must fit this much more of the roof to win
REGISTER_CELLS = 3  # search footprint-to-LiDAR shifts up to 1.5 m


def _shifted(mask, dr, dc):
    """mask moved dr rows down and dc columns right, zero-filled."""
    out = np.zeros_like(mask)
    h, w = mask.shape
    out[max(dr, 0):h + min(dr, 0), max(dc, 0):w + min(dc, 0)] = mask[max(-dr, 0):h + min(-dr, 0),
                                                                     max(-dc, 0):w + min(-dc, 0)]
    return out


def rect_frame(poly):
    """(u, v, center, half_length, half_width) of a polygon's minimum
    rotated rectangle: u along the long side, v across it."""
    mrr = poly.minimum_rotated_rectangle
    pts = np.asarray(mrr.exterior.coords)[:4]
    e1, e2 = pts[1] - pts[0], pts[2] - pts[1]
    l1, l2 = float(np.hypot(*e1)), float(np.hypot(*e2))
    if l1 >= l2:
        u, v, half_l, half_w = e1 / l1, e2 / l2, l1 / 2, l2 / 2
    else:
        u, v, half_l, half_w = e2 / l2, e1 / l1, l2 / 2, l1 / 2
    return tuple(map(float, u)), tuple(map(float, v)), tuple(map(float, pts.mean(axis=0))), half_l, half_w


def _st(m, e, n):
    c, u, v = m["center"], m["u"], m["v"]
    de, dn = np.asarray(e, float) - c[0], np.asarray(n, float) - c[1]
    return de * u[0] + dn * u[1], de * v[0] + dn * v[1]


def _side_distance(side, s, t, half_l, half_w):
    return {"s+": half_l - s, "s-": half_l + s, "t+": half_w - t, "t-": half_w + t}[side]


def _eave_distance(sides, s, t, half_l, half_w):
    return np.minimum.reduce([np.asarray(_side_distance(x, s, t, half_l, half_w), float) for x in sides])


def model_z(m, e, n):
    """Height above the base of a fitted roof at local (e, n)."""
    s, t = _st(m, e, n)
    d = _eave_distance(m["sides"], s, t, m["half_l"], m["half_w"])
    return m["eave"] + m["k"] * np.maximum(d, 0.0)


def _robust_line(x, z):
    """z = a + b x, refit twice on the cells near the line (drops chimneys,
    dormers and branches)."""
    keep = np.ones(len(x), bool)
    a = b = 0.0
    for tol in (None, 0.75, FIT_TOL_M):
        if tol is not None:
            keep = np.abs(z - (a + b * x)) < tol
            if keep.sum() < 8:
                break
        b, a = np.polyfit(x[keep], z[keep], 1)
    return float(a), float(b)


def roof_model(fp, dsm, ground, origin, res=PITCH_RES_M, base=None, reasons=None):
    """A pitched roof fitted to one footprint's LiDAR surface, or None.
    Returns {"kind", "sides", "eave", "ridge", "k", "pitch_deg",
    "fit_share", "flat_share", "shift" (the LiDAR roof's offset from the
    footprint, m east and north), "u", "v", "center", "half_l", "half_w"},
    heights in m above `base` (the footprint's ground;
    lidar.footprint_base). With `reasons` (a Counter), refusals are counted:
    not_simple, no_grid, too_small, flat, no_fit, height."""
    from rasterio.features import geometry_mask

    def refuse(why):
        if reasons is not None:
            reasons[why] += 1
        return None

    if fp.geom_type != "Polygon" or fp.interiors:
        return refuse("not_simple")
    u, v, c, half_l, half_w = rect_frame(fp)
    if fp.area < SIMPLE_MIN * 4 * half_l * half_w:
        return refuse("not_simple")
    w = roof_window(fp, dsm, ground, origin, res, pad=2 + REGISTER_CELLS)
    if w is None:
        return refuse("no_grid")
    inner = fp.buffer(-EDGE_M)
    if inner.is_empty:
        return refuse("too_small")
    msk = geometry_mask([inner], out_shape=w["win"].shape, transform=w["tf"], invert=True)
    if msk.sum() < MIN_CELLS:
        return refuse("too_small")
    if base is None:
        g = w["gnd"][~np.isnan(w["gnd"])]
        base = float(np.median(g)) if g.size else 0.0
    # Register the footprint to the LiDAR roof: the shift (whole cells, up to
    # REGISTER_CELLS) that best overlaps the footprint with cells raised above
    # MIN_EAVE_M. On the Northeast spot many clean gables failed only because
    # the roof sat up to a meter off the City outline. The model is fit in the
    # shifted frame and drawn on the City footprint, so the render keeps
    # matching the footprints the alignment check uses
    raised = (w["win"] - base) > MIN_EAVE_M
    full = geometry_mask([fp], out_shape=raised.shape, transform=w["tf"], invert=True)
    best_iou, dr, dc = -1.0, 0, 0
    for r_ in range(-REGISTER_CELLS, REGISTER_CELLS + 1):
        for c_ in range(-REGISTER_CELLS, REGISTER_CELLS + 1):
            sh = _shifted(full, r_, c_)
            inter = np.count_nonzero(sh & raised)
            iou = inter / max(np.count_nonzero(sh | raised), 1)
            # ties go to the smaller shift
            if iou > best_iou + 1e-9 or (abs(iou - best_iou) <= 1e-9 and r_ * r_ + c_ * c_ < dr * dr + dc * dc):
                best_iou, dr, dc = iou, r_, c_
    msk = _shifted(msk, dr, dc)
    rows, cols = np.nonzero(msk)
    # Cell (row, col) of the roof corresponds to footprint cell (row - dr, col - dc)
    e = origin[0] + (w["c0"] + cols - dc + 0.5) * res
    n = origin[1] - (w["r0"] + rows - dr + 0.5) * res
    z = w["win"][rows, cols] - base
    frame = {"u": u, "v": v, "center": c, "half_l": half_l, "half_w": half_w}
    s, t = _st(frame, e, n)
    flat_share = float(np.mean(np.abs(z - np.median(z)) < FIT_TOL_M))
    best = None
    for kind, sides in ROOF_MODELS:
        x = _eave_distance(sides, s, t, half_l, half_w)
        a, b = _robust_line(x, z)
        pitch = float(np.degrees(np.arctan(b)))
        if not PITCH_RANGE_DEG[0] <= pitch <= PITCH_RANGE_DEG[1]:
            continue
        share = float(np.mean(np.abs(z - (a + b * x)) < FIT_TOL_M))
        if best is None or share > best["fit_share"] + TIE_SHARE:
            best = {"kind": kind, "sides": sides, "eave": a, "k": b, "pitch_deg": pitch, "fit_share": share}
    if best is None or best["fit_share"] < MIN_FIT_SHARE:
        return refuse("flat" if flat_share >= MIN_FIT_SHARE else "no_fit")
    if best["fit_share"] < flat_share + MIN_GAIN:
        return refuse("flat")
    # The ridge: the highest point of the model over the rectangle
    gs, gt = np.meshgrid(np.linspace(-half_l, half_l, 41), np.linspace(-half_w, half_w, 41))
    ridge = best["eave"] + best["k"] * float(_eave_distance(best["sides"], gs, gt, half_l, half_w).max())
    if best["eave"] < MIN_EAVE_M or ridge > MAX_RIDGE_M:
        return refuse("height")
    return {**best, "ridge": ridge, "flat_share": flat_share, "shift": (dc * res, -dr * res), **frame}


def _regions(m):
    """The roof's planar regions as world polygons: for each eave side, the
    part of the (slightly enlarged) rectangle where that side is the nearest
    eave. Each is the rectangle cut by half-planes d_side <= d_other, all
    linear in (s, t)."""
    L, W = m["half_l"] + 1.0, m["half_w"] + 1.0
    big = 4 * (L + W)
    c, u, v = m["center"], m["u"], m["v"]

    def world(pts):
        return Polygon([(c[0] + s * u[0] + t * v[0], c[1] + s * u[1] + t * v[1]) for s, t in pts])

    # d = a0 + a1 s + a2 t for each side
    coef = {"s+": (m["half_l"], -1, 0), "s-": (m["half_l"], 1, 0), "t+": (m["half_w"], 0, -1),
            "t-": (m["half_w"], 0, 1)}
    out = []
    for side in m["sides"]:
        reg = Polygon([(-L, -W), (L, -W), (L, W), (-L, W)])
        for other in m["sides"]:
            if other == side:
                continue
            # keep d_side - d_other <= 0: g0 + g1 s + g2 t <= 0
            g = np.subtract(coef[side], coef[other])
            if abs(g[1]) < 1e-12 and abs(g[2]) < 1e-12:
                continue
            nrm = np.array([g[1], g[2]], float)
            p0 = -g[0] * nrm / (nrm @ nrm)  # a point on the line
            tang = np.array([-nrm[1], nrm[0]]) / np.hypot(*nrm)
            back = -nrm / np.hypot(*nrm)  # into the kept side
            half = Polygon([tuple(p0 - tang * big), tuple(p0 + tang * big),
                            tuple(p0 + tang * big + back * big), tuple(p0 - tang * big + back * big)])
            reg = reg.intersection(half)
        if not reg.is_empty and reg.area > 1e-9:
            out.append(world(list(reg.exterior.coords)[:-1]))
    return out


def roof_mesh(fp, m):
    """Triangles of a fitted roof clipped to the footprint, and the
    footprint's ring with the ridge and hip crossings added (so gable-end
    and party walls rise to the roof). Returns {"ring": [[e, n], ...]
    (counter-clockwise, open), "ring_z": [...], "v": [[e, n, z], ...], "t":
    [[i, j, k], ...] (counter-clockwise from above)}, heights above the
    base."""
    import shapely
    from shapely.geometry import LineString

    regions = _regions(m)
    verts, index, tris = [], {}, []

    def vid(x, y):
        key = (round(x, 3), round(y, 3))
        if key not in index:
            index[key] = len(verts)
            verts.append([float(x), float(y), float(model_z(m, x, y))])
        return index[key]

    for reg in regions:
        piece = reg.intersection(fp)
        for g in getattr(piece, "geoms", [piece]):
            if g.geom_type != "Polygon" or g.area < 1e-6:
                continue
            for tri in shapely.constrained_delaunay_triangles(g).geoms:
                if tri.area < 1e-8:
                    continue
                ids = [vid(x, y) for x, y in list(tri.exterior.coords)[:3]]
                a, b, cc = (verts[i] for i in ids)
                if (b[0] - a[0]) * (cc[1] - a[1]) - (b[1] - a[1]) * (cc[0] - a[0]) < 0:
                    ids = ids[::-1]
                tris.append(ids)
    # Ridge and hip lines: the region boundaries
    from shapely.ops import unary_union

    lines = unary_union([r.boundary for r in regions]) if len(regions) > 1 else None
    ring = list(orient(Polygon(fp.exterior), 1.0).exterior.coords)[:-1]
    out = []
    for i, p in enumerate(ring):
        q = ring[(i + 1) % len(ring)]
        out.append(p)
        if lines is None:
            continue
        seg = LineString([p, q])
        hit = seg.intersection(lines)
        cross = []
        for h in getattr(hit, "geoms", [hit]):
            if h.geom_type == "Point":
                dist = seg.project(h)
                if 1e-4 < dist < seg.length - 1e-4:
                    cross.append((dist, (h.x, h.y)))
        out += [xy for _, xy in sorted(cross)]
    ring_z = [float(model_z(m, x, y)) for x, y in out]
    return {"ring": [[float(x), float(y)] for x, y in out], "ring_z": ring_z, "v": verts, "t": tris}


CORNICE_BITS = 4 | 32  # facades.BAND_CORNICE | BAND_HEAVY_CORNICE: they follow the wall top, which on a
# fitted roof is the gable's rake, and would paint whole gable ends dark


def roof3d_building(b, fp, m):
    """The scene record for a building with a fitted roof: one part
    ("<id>-0", like a LiDAR part), its ring with the ridge crossings, h =
    the ridge, and "roof3d": {"ring_z": wall-top height at each ring vertex,
    "t": roof triangles (indices into "v"), "v": [[e, n, z], ...]} in local
    meters, 0.01 m. render/render.js builds the walls and roof from these;
    scripts/09_check_alignment.py projects the same numbers. Keys of `b`
    other than id, h and polys carry over (facade, fixed_color, ...), with
    the cornice bands dropped from the facade."""
    mesh = roof_mesh(fp, m)
    r2 = lambda x: round(float(x), 2)  # noqa: E731
    v = [[r2(e), r2(n), r2(z)] for e, n, z in mesh["v"]]
    rest = {k: val for k, val in b.items() if k not in ("id", "h", "polys")}
    if rest.get("facade") and rest["facade"].get("b", 0) & CORNICE_BITS:
        rest["facade"] = {**rest["facade"], "b": rest["facade"]["b"] & ~CORNICE_BITS}
    return {**rest, "id": f"{b['id']}-0", "h": max(z for _, _, z in v),
            "polys": [[[[r2(e), r2(n)] for e, n in mesh["ring"]]]],
            "roof3d": {"ring_z": [r2(z) for z in mesh["ring_z"]], "t": mesh["t"], "v": v}}
