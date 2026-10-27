"""Repaint open water in a redraw with one consistent style.

Used on the stitched mosaic (scripts/10_repaint_water.py) and on single
training targets at any zoom (scripts/13_build_trainset.py), so the river
looks the same everywhere and the fine-tuned model learns one water style
instead of the four colors Gemini picked frame by frame.

A pixel is repainted only if all three hold:
  1. USGS NHD says it is water (both banks of the Delaware);
  2. the render shows open water there: its color is within `threshold` of
     the river's median render color. This keeps the bridge deck and its
     shadow, piers and boats, which sit inside the NHD polygon;
  3. no building covers it (building silhouette masks, slightly grown).

Views are described by their top-left corner (gx0, gy0) in MOSAIC pixel
coordinates and `scale` = mosaic pixels per image pixel (1 for lattice
frames, 0.5 for 2x zoomed quarters). The ripple pattern is laid out in
mosaic coordinates so it lines up across frames and zooms.

The colors are a style choice: a muted blue-grey, though the real Delaware
is brownish (the same choice tiny.london made for the Thames).
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from .sources import RAW

WATER_STYLE = {
    "base": (88, 124, 140),
    "ripple": (122, 158, 170),
    "shore": (66, 98, 114),
    "shore_px": 4,
    # One ripple dash starts on roughly 1 in this many 2x2 art pixels
    "ripple_rarity": 140,
    "ripple_len_art_px": 3,
}


def nhd_geometry(cfg, frame, cam, x_origin: float, y_origin: float):
    """NHD water polygons in mosaic pixel coordinates (screen px minus the
    lattice origin)."""
    return water_geometry(cfg, frame, cam, x_origin, y_origin, "water_nhd")


def water_geometry(cfg, frame, cam, x_origin: float, y_origin: float, suffix: str):
    """Polygons of data/raw/<area>_<suffix>.geojson (NHD "water_nhd", PWD
    "water") in mosaic pixel coordinates; empty if the file is missing."""
    path = RAW / f"{cfg['name']}_{suffix}.geojson"
    if not path.exists():
        return Polygon()
    data = json.loads(path.read_text())
    polys = []
    for feat in data["features"]:
        g = shape(feat["geometry"])
        for p in [g] if g.geom_type == "Polygon" else list(g.geoms):
            rings = []
            for ring in [p.exterior, *p.interiors]:
                lon, lat = np.asarray(ring.coords).T[:2]
                e, n = frame.to_local(lon, lat)
                sx, sy = cam.world_to_screen(e, n, 0.0)
                rings.append(list(zip(sx - x_origin, sy - y_origin)))
            polys.append(Polygon(rings[0], rings[1:]).buffer(0))
    return unary_union(polys)


def rasterize_view(geom, gx0: float, gy0: float, scale: float, width: int, height: int) -> np.ndarray:
    """Boolean mask of `geom` (mosaic coords) for a width x height view."""
    view = box(gx0, gy0, gx0 + width * scale, gy0 + height * scale)
    clipped = geom.intersection(view)
    # mosaic -> image pixels: (x - gx0) / scale
    local = affine_transform(clipped, [1 / scale, 0, 0, 1 / scale, -gx0 / scale, -gy0 / scale])
    img = Image.new("L", (width, height))
    d = ImageDraw.Draw(img)
    for p in [local] if local.geom_type == "Polygon" else list(getattr(local, "geoms", [])):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        d.polygon(list(p.exterior.coords), fill=255)
        for hole in p.interiors:
            d.polygon(list(hole.coords), fill=0)
    return np.asarray(img) > 127


def color_model(render: np.ndarray, nhd: np.ndarray, buildings: np.ndarray):
    """Median open-water color of the render and the distance threshold,
    sampled well inside the NHD polygon (31 px erosion) and off buildings."""
    core = np.asarray(Image.fromarray(nhd.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(31))) > 127
    sample = render[core & ~buildings].astype(int)
    median = np.median(sample, axis=0)
    typical = np.median(np.abs(sample - median).max(axis=1))
    return median, max(30.0, 4.0 * float(typical))


def grow(mask: np.ndarray, px: int = 5) -> np.ndarray:
    """Grow building silhouettes slightly so a repaint never nibbles their edges."""
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(px))) > 127


def water_mask(render: np.ndarray, nhd: np.ndarray, buildings: np.ndarray, median, threshold: float) -> np.ndarray:
    dist = np.abs(render.astype(int) - np.asarray(median)).max(axis=2)
    wet = Image.fromarray(((dist < threshold) * 255).astype(np.uint8))
    # Median filter removes speckle in the color test without eating the
    # bridge or piers, which are far larger than the filter
    wet = np.asarray(wet.filter(ImageFilter.MedianFilter(9))) > 127
    return nhd & wet & ~buildings


def ripple_mask(width: int, height: int, gx0: float = 0, gy0: float = 0, scale: float = 1.0, style=WATER_STYLE):
    """Sparse horizontal dashes on a 2-mosaic-pixel art grid, placed by a
    fixed hash of mosaic position so the pattern is identical in every view."""
    ys, xs = np.mgrid[0:height, 0:width]
    ax = np.floor((gx0 + xs * scale) / 2).astype(np.int64)
    ay = np.floor((gy0 + ys * scale) / 2).astype(np.int64)
    dash = np.zeros((height, width), bool)
    for k in range(style["ripple_len_art_px"]):
        h = ((ax - k) * 73856093) ^ (ay * 19349663)
        dash |= (h % style["ripple_rarity"]) == 0
    return dash


def apply(redraw: np.ndarray, water: np.ndarray, gx0=0, gy0=0, scale=1.0, style=WATER_STYLE) -> np.ndarray:
    h, w = water.shape
    shore = water & ~(
        np.asarray(Image.fromarray(water.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(2 * style["shore_px"] + 1)))
        > 127
    )
    ripples = ripple_mask(w, h, gx0, gy0, scale, style) & water & ~shore
    out = redraw.copy()
    out[water] = style["base"]
    out[ripples] = style["ripple"]
    out[shore] = style["shore"]
    return out
