"""Find and repair water the drawing model invents on land.

The model sometimes paints a pool where the render shows a shaded courtyard
(atlas_cityhall_fac: a light-blue pool beside City Hall, 5,570 px in
frame_01_01, median RGB (114, 163, 181)). The water repaint
(waterpaint.py) only works inside mapped water (NHD), so it can't see these.

A blob is flagged when all hold:
- its pixels are water-colored (water_like: the repaint's own water style
  and the invented pool share one hue band; see WATER_BAND);
- it is at least MIN_AREA_PX;
- it lies outside mapped water (NHD and PWD, grown) and outside building
  silhouettes (blue glass curtain walls are walls, not pools).
Exemptions, so real water and missing roofs stay: the render (the aerial) is
itself water-colored (same hue band) under 30% or more of the blob; an NWI
wetland covers 20% or more of it; it is a flat light rectangle in the aerial
(a roof the scene is missing); or a City swimming pool
(PPR_Swimming_Pools) is within reach.

Repair (repair): the blob, its small holes (the model's ripple dashes)
and its antialiased bluish fringe are filled flat with the surrounding
drawing's typical color (a color the drawing already uses), or its typical
green where the aerial under the blob is clearly green (turf, lawn). Mapping the
aerial's texture onto the drawing's palette was tried: it left noisy dark
blotches.
"""

from __future__ import annotations

import numpy as np

# Hue (degrees), saturation, value bands of water-like color, from measured
# pixels: the invented pool H 197 S 0.37 V 0.71; the repaint's water style
# base H 199 S 0.37 V 0.55, ripple H 195 S 0.28 V 0.67, shore H 200 S 0.42
# V 0.45; invented water in the regions' dry run (a turf field drawn as a
# pool: V 0.68-0.77; railroad cuts drawn as canals: V p10 0.46). Value from
# 0.44: shaded blue-gray pavement (South Philly near the stadiums: V
# 0.37-0.42, S 0.22-0.27) was the dry run's false positive. Lawns (H ~100),
# brick (H ~10-25) and gray pavement (S < 0.1) are far outside
WATER_BAND = {"h": (185.0, 215.0), "s": (0.18, 0.60), "v": (0.44, 0.85)}
MIN_AREA_PX = 400  # ~34 m² at 0.293 m/px: a small courtyard pool; smaller specks are window glints and signs
RENDER_WATER_SHARE = 0.3  # exempt if this share of the blob is water-colored (WATER_BAND) in the render
# NWI wetlands (USFWS, fetched by 04k_fetch_wetlands.py): a blob this much
# inside a mapped wetland, pond or lake may be real water missing from NHD
# and PWD (lower South Philly basins and mudflats). NWI polygons were drawn
# from older imagery and are coarse, so full containment is too strict; 20%
# is real overlap while a blob merely touching a wetland edge stays flagged
WETLAND_SHARE = 0.20
# A flat roof the scene is missing (Upper North: a gym's light-blue roof in
# three sections, as seen from neighboring frames: rectangularity 0.79-0.88
# (buildings drawn in front cut into one section), aerial V 0.74-0.79,
# luminance std 10.7-29.3 (roof vents), S 0.08-0.09). The aerial's value
# and saturation separate roofs from the water to fix: the turf field drawn
# as a pool (rectangularity 0.76, aerial V 0.44, S 0.39), the City Hall pool
# (0.49, V 0.31)
ROOF_RECT = 0.78
ROOF_MIN_V = 0.55
ROOF_MAX_LUM_STD = 32.0
ROOF_MAX_S = 0.20
# Aerial clearly green under a blob (turf, lawn): fill with the drawing's
# green, not the ring median (the turf field came out gray). Measured turf:
# H 61, S 0.39; the pale West Philly basin (H 55) and a railroad cut (H 44)
# stay with the ring median
GREEN_AERIAL = {"h": (58.0, 170.0), "s_min": 0.20}
# Drawn lawn greens. Hue 75-140 and saturation >= 0.25: the first band
# (hue 70-170, sat 0.15) accepted the teal-gray edge of the turf-field pool
# (hue 157, sat 0.15) as "green" and filled the field gray-teal
GREEN_RING = {"h": (75.0, 140.0), "s_min": 0.25, "v": (0.30, 0.85)}
# Invented lawn in a courtyard: the aerial under it isn't green (City Hall's
# courtyard is shadowed paving: hue ~30, sat < 0.15)
RING_PX = 10
HOLE_FILL_PX = 64  # holes smaller than this inside a blob are the model's ripple dashes; bigger ones are objects
FRINGE_PX = 3  # antialiased bluish edge pixels just outside WATER_BAND go with the blob
# The fringe's looser band: same hues, any visible tint
FRINGE_BAND = {"h": (180.0, 222.0), "s": (0.08, 0.65), "v": (0.30, 0.92)}


def _hsv(rgb):
    a = np.asarray(rgb, float) / 255.0
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.zeros_like(mx)
    m = d > 1e-9
    hr = m & (mx == r)
    hg = m & ~hr & (mx == g)
    hb = m & ~hr & ~hg
    h[hr] = ((g - b)[hr] / d[hr]) % 6
    h[hg] = (b - r)[hg] / d[hg] + 2
    h[hb] = (r - g)[hb] / d[hb] + 4
    s = np.where(mx > 0, d / np.maximum(mx, 1e-9), 0.0)
    return h * 60.0, s, mx


def water_like(rgb) -> np.ndarray:
    h, s, v = _hsv(rgb)
    (h0, h1), (s0, s1), (v0, v1) = WATER_BAND["h"], WATER_BAND["s"], WATER_BAND["v"]
    return (h >= h0) & (h <= h1) & (s >= s0) & (s <= s1) & (v >= v0) & (v <= v1)


def find_blobs(drawing, render, water_ok, buildings, pools_px=(), pool_radius_px=85, min_area=MIN_AREA_PX,
               wetlands=None):
    """Water-colored blobs on open ground. drawing, render: (H, W, 3) uint8;
    water_ok: mapped water grown by a margin; buildings: grown silhouettes.
    pools_px: City pool points in these pixel coordinates (x, y).
    wetlands: optional bool mask of NWI wetland polygons.

    Returns [{"area_px", "bbox": [x0, y0, x1, y1], "mask_bbox": bool array
    over bbox, "exempt": None | reason}]."""
    from rasterio.features import rasterize, shapes
    from shapely.geometry import Point, shape

    cand = water_like(drawing) & ~water_ok & ~buildings
    if cand.sum() < min_area:
        return []
    out = []
    for geom, _ in shapes(cand.astype(np.uint8), mask=cand, connectivity=8):
        poly = shape(geom)
        if poly.area < min_area:
            continue
        from shapely.geometry import Polygon

        poly = Polygon(poly.exterior, [h for h in poly.interiors if Polygon(h).area >= HOLE_FILL_PX])
        x0, y0, x1, y1 = (int(round(v)) for v in poly.bounds)
        from rasterio.transform import Affine

        m = rasterize([(poly, 1)], out_shape=(y1 - y0, x1 - x0), transform=Affine.translation(x0, y0), fill=0,
                      dtype="uint8").astype(bool)
        exempt = None
        # The aerial shows water there too (a fountain, a pool): its pixels are
        # in the same water hue band. (The repaint's color model, fitted to
        # brown river water, also accepts shaded gray pavement: it exempted
        # the invented pool beside City Hall)
        if water_like(render[y0:y1, x0:x1][m]).mean() >= RENDER_WATER_SHARE:
            exempt = "render shows water"
        if exempt is None and any(poly.distance(Point(p)) <= pool_radius_px for p in pools_px):
            exempt = "city pool"
        if exempt is None and wetlands is not None and wetlands[y0:y1, x0:x1][m].mean() >= WETLAND_SHARE:
            exempt = "NWI wetland"
        if exempt is None and poly.area / max(poly.minimum_rotated_rectangle.area, 1e-9) >= ROOF_RECT:
            rp = render[y0:y1, x0:x1][m]
            _, s_, v = _hsv(rp)
            lum = rp.astype(float) @ np.array([0.299, 0.587, 0.114])
            if np.median(v) > ROOF_MIN_V and lum.std() < ROOF_MAX_LUM_STD and np.median(s_) < ROOF_MAX_S:
                exempt = "roof-like (building missing)"
        out.append({"area_px": int(round(poly.area)), "bbox": [x0, y0, x1, y1], "mask_bbox": m, "exempt": exempt})
    return out


def _band(rgb, band):
    h, s_, v = _hsv(rgb)
    (h0, h1), (s0, s1), (v0, v1) = band["h"], band["s"], band["v"]
    return (h >= h0) & (h <= h1) & (s_ >= s0) & (s_ <= s1) & (v >= v0) & (v <= v1)


def _grow(mask, px):
    from PIL import Image, ImageFilter

    img = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * px + 1))
    return np.asarray(img) > 127


def _lawn_green(rgb):
    h, s_, v = _hsv(rgb)
    return ((h >= GREEN_RING["h"][0]) & (h <= GREEN_RING["h"][1]) & (s_ >= GREEN_RING["s_min"])
            & (v >= GREEN_RING["v"][0]) & (v <= GREEN_RING["v"][1]))


COURTYARD_REACH_PX = 85  # ~25 m: how far past the footprint hole a confirmed courtyard's lawn is taken
COURTYARD_PAVING_MAX_S = 0.18  # aerial saturation: City Hall's paving < 0.15, dormant grass 0.25-0.40


def courtyard_lawn(drawing, render, buildings, holes, min_area=MIN_AREA_PX):
    """Lawn the model drew in a paved courtyard. holes: bool mask of courtyard
    holes in building footprints (a hole in ONE building's outline, as at
    City Hall). Open ground merely enclosed by separate buildings doesn't
    count: rowhouse block interiors are real backyards, and with an
    enclosure test 207 of them were flagged (dormant brown in the March
    aerial, correctly drawn green). A drawn-green blob in a hole is invented
    when the aerial there is paving (low saturation, not green or dormant
    grass). Returns blobs in find_blobs' format, filled with the ring's
    non-green paving."""
    from rasterio.features import rasterize, shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape

    # A courtyard is a component of open ground that overlaps a footprint
    # hole by at least min_area. The hole can be smaller than the visible
    # courtyard (at City Hall it covered only part of the drawn grass), so
    # once the courtyard is confirmed every greenish pixel in it is taken,
    # including shaded grass outside the strict lawn band
    if (_lawn_green(drawing) & holes & ~buildings).sum() < min_area:
        return []
    h_, s_, v_ = _hsv(drawing)
    greenish = (h_ >= 60) & (h_ <= 160) & (s_ >= 0.15) & (v_ >= 0.12)
    near = _grow(holes, COURTYARD_REACH_PX)
    out = []
    open_ground = ~buildings
    for geom, _ in shapes(open_ground.astype(np.uint8), mask=open_ground, connectivity=4):
        poly = shape(geom)
        if poly.area < min_area:
            continue
        bx0, by0, bx1, by1 = (int(round(v)) for v in poly.bounds)
        comp = rasterize([(poly, 1)], out_shape=(by1 - by0, bx1 - bx0), transform=Affine.translation(bx0, by0),
                         fill=0, dtype="uint8").astype(bool)
        if (comp & holes[by0:by1, bx0:bx1]).sum() < min_area:
            continue
        # Only near the hole: a courtyard open to the street joins the whole
        # street network as open ground, and parks beyond it must stay green
        lawn = comp & greenish[by0:by1, bx0:bx1] & near[by0:by1, bx0:bx1]
        if lawn.sum() < min_area:
            continue
        ys, xs = np.nonzero(lawn)
        x0, y0, x1, y1 = bx0 + xs.min(), by0 + ys.min(), bx0 + xs.max() + 1, by0 + ys.max() + 1
        m = lawn[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0]
        _, sr, _ = _hsv(render[y0:y1, x0:x1][m])
        if np.median(sr) >= COURTYARD_PAVING_MAX_S:
            continue
        out.append({"area_px": int(m.sum()), "bbox": [int(x0), int(y0), int(x1), int(y1)], "mask_bbox": m, "exempt": None,
                    "kind": "courtyard lawn", "fill": "non_green"})
    return out


def repair(drawing, render, blobs):
    """A copy of drawing with every non-exempt blob (plus its bluish fringe)
    filled flat with the surrounding drawing's typical color: the ring pixel
    nearest the ring's median, so the fill is a color the drawing already
    uses. A flat fill suits the pixel-art style; mapping the aerial's
    texture onto the ring's palette was tried and left noisy dark blotches.
    render is unused by the fill (kept for the call signature)."""
    out = drawing.copy()
    h, w = drawing.shape[:2]
    bluish = _band(drawing, FRINGE_BAND)
    for b in blobs:
        if b["exempt"]:
            continue
        x0, y0, x1, y1 = b["bbox"]
        full = np.zeros((h, w), bool)
        full[y0:y1, x0:x1] = b["mask_bbox"]
        full |= _grow(full, FRINGE_PX) & bluish
        if b.get("fill") != "non_green":
            # The blob's whole extent: the model's dark shore outline and
            # darker patches connected to it (SHORE_BAND, up to SHORE_REACH_PX),
            # then every hole inside (big ripple dashes, patches). Roxborough's
            # field pond kept a blue ring and dashes without this (Nov. 4)
            _, ss, vv = _hsv(drawing)
            shore = _band(drawing, SHORE_BAND)
            full = _extent(full, shore, shore | ((ss < 0.15) & (vv > 0.75)))
        ring = _grow(full, RING_PX) & ~full & ~bluish
        src = drawing[ring]
        if not len(src):
            continue
        h_r, s_r, _ = _hsv(render[full])
        green_aerial = (GREEN_AERIAL["h"][0] <= np.median(h_r) <= GREEN_AERIAL["h"][1]
                        and np.median(s_r) >= GREEN_AERIAL["s_min"])
        if b.get("fill") == "non_green":
            # Invented lawn: fill with the ring's paving, never its greens
            keep = ~_lawn_green(src)
            if keep.any():
                src = src[keep]
        elif green_aerial:
            greens = src[_lawn_green(src)]
            if not len(greens):
                # No lawn right around the blob (a turf field ringed by
                # paving): use the window's drawn lawn color
                window = drawing[~full]
                greens = window[_lawn_green(window)]
            if len(greens):
                src = greens
        med = np.median(src.astype(float), axis=0)
        out[full] = src[np.argmin(((src.astype(float) - med) ** 2).sum(axis=1))]
    return out


SHORE_BAND = {"h": (180.0, 225.0), "s": (0.08, 0.80), "v": (0.10, 0.95)}  # fringe plus the dark navy shore line
SHORE_REACH_PX = 12


def _fill_holes(mask, fillable=None):
    """mask with its enclosed holes filled. With `fillable` (bool array),
    a hole of HOLE_FILL_PX or more is filled only if most of it is fillable
    (water colors, ripple dashes); bigger holes with other content are
    objects drawn in the water (a building, a dock) and stay."""
    from PIL import Image, ImageDraw
    from rasterio.features import rasterize, shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape

    ys, xs = np.nonzero(mask)
    if not len(ys):
        return mask
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub = np.pad(mask[y0:y1, x0:x1], 1)
    img = Image.fromarray(np.where(sub, 255, 0).astype(np.uint8))
    ImageDraw.floodfill(img, (0, 0), 128)
    holes = (np.asarray(img) == 0)[1:-1, 1:-1]
    out = mask.copy()
    if fillable is None:
        out[y0:y1, x0:x1] |= holes
        return out
    fsub = fillable[y0:y1, x0:x1]
    for geom, _ in shapes(holes.astype(np.uint8), mask=holes, connectivity=4):
        comp = rasterize([(shape(geom), 1)], out_shape=holes.shape, transform=Affine.identity(), fill=0,
                         dtype="uint8").astype(bool)
        if comp.sum() < HOLE_FILL_PX or fsub[comp].mean() >= 0.5:
            out[y0:y1, x0:x1] |= comp
    return out


def _extent(full, shore, fillable):
    """Grow `full` through connected `shore` pixels up to SHORE_REACH_PX,
    then fill its holes (fillable: water colors and ripple dashes)."""
    full = _fill_holes(full, fillable)
    for _ in range(SHORE_REACH_PX):
        grown = full | (_grow(full, 1) & shore)
        if (grown == full).all():
            break
        full = grown
    return _fill_holes(full, fillable)


def apply_holds(blobs, gx, gy, holds):
    """Mark blobs on the reviewed hold list as exempt ("held: <reason>").

    holds: [{"bbox": [x0, y0, x1, y1] in the area's mosaic px, "reason": ...}].
    A blob is held when its center, shifted by the window origin (gx, gy),
    falls inside a hold box. The list is for flags a person reviewed and
    couldn't confirm as invented (mudflats missing from the wetland map, a
    court that really is blue), so repair leaves them as drawn. Blobs that
    are already exempt keep their reason."""
    if not holds:
        return blobs
    out = []
    for b in blobs:
        b = dict(b)
        if not b["exempt"]:
            x0, y0, x1, y1 = b["bbox"]
            cx, cy = (x0 + x1) / 2 + gx, (y0 + y1) / 2 + gy
            for h in holds:
                hx0, hy0, hx1, hy1 = h["bbox"]
                if hx0 <= cx <= hx1 and hy0 <= cy <= hy1:
                    b["exempt"] = f"held: {h['reason']}"
                    break
        out.append(b)
    return out
