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
GREEN_RING = {"h": (70.0, 170.0), "s_min": 0.15}  # drawn greens in the ring
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
        ring = _grow(full, RING_PX) & ~full & ~bluish
        src = drawing[ring]
        if not len(src):
            continue
        h_r, s_r, _ = _hsv(render[full])
        green_aerial = (GREEN_AERIAL["h"][0] <= np.median(h_r) <= GREEN_AERIAL["h"][1]
                        and np.median(s_r) >= GREEN_AERIAL["s_min"])
        if green_aerial:
            h_s, s_s, _ = _hsv(src)
            greens = src[(h_s >= GREEN_RING["h"][0]) & (h_s <= GREEN_RING["h"][1]) & (s_s >= GREEN_RING["s_min"])]
            if len(greens):
                src = greens
        med = np.median(src.astype(float), axis=0)
        out[full] = src[np.argmin(((src.astype(float) - med) ** 2).sum(axis=1))]
    return out
