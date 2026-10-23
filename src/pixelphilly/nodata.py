"""Where the city's aerial imagery ends, show only the background.

The City of Philadelphia's imagery stops partway across the Delaware; on the
New Jersey side the tile server returns HTTP 404 (recorded by
scripts/03_fetch_imagery.py as `<y>_<x>.none` markers). The scene builder
fills those tiles with flat grey, and the AI model, given featureless input,
invents a scene there: on the downtown map it drew a seaplane, a bridge,
buildings and a large cartoon person. Nothing it draws there is grounded in
data, so scripts/10_repaint_water.py paints every such pixel with the
viewer's background color instead.

Missing tiles are found from the area's tile range in data/raw/MANIFEST.json
and projected to the ground plane (h = 0). Ground level is correct: building
and tree footprints are Philadelphia-only, so nothing stands in these areas.
"""

from __future__ import annotations

import json
import math

import numpy as np
from PIL import Image, ImageFilter
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

from .projection import render_ground_polygon
from .sources import RAW
from .waterpaint import rasterize_view

SERVICE = "CityImagery_2024_3in"

# The viewer's haze blue-grey (like tiny.london's sky). scripts/16_build_tiles.py
# fills lattice cells outside the area with it, so cleared no-data pixels
# blend into the empty corners around the map.
BACKGROUND = (204, 214, 227)

# The model does not stop inventing exactly at the tile edge: objects drawn
# on the grey area spill a little onto real imagery, and the render blurs the
# texture boundary across a few pixels. Growing the mask by this much clears
# that fringe too, at the cost of a thin strip of real (mostly water) pixels.
NODATA_MARGIN_PX = 16


def _tile_box(x: int, y: int, z: int):
    """WGS84 bounds of Web Mercator tile (x, y) at zoom z."""
    n = 2**z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return box(lon0, lat0, lon1, lat1)


def missing_tile_boxes(cfg) -> list[Polygon]:
    """WGS84 boxes of the area's tiles that have no imagery.

    A tile counts as missing whether the server returned 404 (a `.none`
    marker) or it was never downloaded: build_mosaic fills both with grey.
    For clipped areas only tiles the kept frames see are considered, the same
    rule 03_fetch_imagery.py uses; tiles outside that polygon are never
    rendered, so they cannot hold invented content.
    """
    z = cfg["imagery_zoom"]
    manifest = json.loads((RAW / "MANIFEST.json").read_text())
    info = manifest[f"imagery/{cfg['name']}/{SERVICE}/{z}"]
    (x0, x1), (y0, y1) = info["tile_x_range"], info["tile_y_range"]
    tile_dir = RAW / "imagery" / SERVICE / str(z)
    boxes = [
        _tile_box(x, y, z)
        for y in range(y0, y1 + 1)
        for x in range(x0, x1 + 1)
        if not (tile_dir / f"{y}_{x}.jpg").exists()
    ]
    if boxes and cfg.get("clip_frames_to_area"):
        ground = prep(render_ground_polygon(cfg))
        boxes = [b for b in boxes if ground.intersects(b)]
    return boxes


def nodata_geometry(cfg, frame, cam, x_origin: float, y_origin: float):
    """Missing imagery in mosaic pixel coordinates (screen px minus the
    lattice origin, as in waterpaint.nhd_geometry). Empty if none."""
    polys = []
    for b in missing_tile_boxes(cfg):
        lon, lat = np.asarray(b.exterior.coords).T
        e, n = frame.to_local(lon, lat)
        sx, sy = cam.world_to_screen(e, n, 0.0)
        polys.append(Polygon(zip(sx - x_origin, sy - y_origin)))
    return unary_union(polys) if polys else Polygon()


def nodata_mask(geom, gx: float, gy: float, w: int, h: int) -> np.ndarray:
    """Boolean mask of `geom` for a w x h view at mosaic (gx, gy), grown by
    NODATA_MARGIN_PX."""
    mask = rasterize_view(geom, gx, gy, 1.0, w, h)
    if not mask.any():
        return mask
    grown = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * NODATA_MARGIN_PX + 1))
    return np.asarray(grown) > 127
