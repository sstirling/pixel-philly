"""Turn the raw downloads into one scene file the three.js renderer can load.

Writes:
  data/processed/<name>_ground.jpg   aerial mosaic used as the ground texture
  data/processed/<name>_scene.json   buildings, trees, camera and frame lattice
  data/processed/<name>_qa.json      height fallbacks, outliers, dropped records

All geometry is converted to local east/north meters (see projection.py).
The ground is treated as flat at 0 m: Old City sits between roughly 3 and 15 m
above sea level, and a slope that gentle doesn't show at this scale.
"""

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# The full mosaic is ~160 MP, above Pillow's decompression-bomb warning
# threshold; it is our own trusted file.
Image.MAX_IMAGE_PIXELS = None
from shapely.geometry import shape
from shapely.validation import make_valid

from pixelphilly.heights import building_height
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.sources import RAW

PROCESSED = REPO_ROOT / "data" / "processed"
TILE = 256
# Chromium's WebGL texture limit is 16384 px on Apple silicon and most
# desktop GPUs (render.js refuses to run if the texture is over the limit).
# At z19 the Old City mosaic is ~12,800 px, so it loads at full resolution.
MAX_TEXTURE_PX = 16384


def merc_px(lon, lat, z):
    """WGS84 -> global Web Mercator pixel coordinates at zoom z."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    scale = TILE * 2**z
    x = (lon + 180.0) / 360.0 * scale
    r = np.radians(lat)
    y = (1.0 - np.log(np.tan(r) + 1.0 / np.cos(r)) / math.pi) / 2.0 * scale
    return x, y


def build_mosaic(cfg):
    manifest = json.loads((RAW / "MANIFEST.json").read_text())
    z = cfg["imagery_zoom"]
    info = manifest[f"imagery/CityImagery_2024_3in/{z}"]
    (x0, x1), (y0, y1) = info["tile_x_range"], info["tile_y_range"]
    tile_dir = RAW / "imagery" / "CityImagery_2024_3in" / str(z)
    w, h = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE
    mosaic = Image.new("RGB", (w, h))
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            with Image.open(tile_dir / f"{ty}_{tx}.jpg") as t:
                mosaic.paste(t.convert("RGB"), ((tx - x0) * TILE, (ty - y0) * TILE))
    return mosaic, (x0 * TILE, y0 * TILE), z


def fit_uv_poly(frame, origin_px, z, size_px, extent_m):
    """Least-squares quadratic map from local (e, n) meters to texture UV.

    Web Mercator's scale changes with latitude, so over ~3 km a plain affine
    fit drifts ~0.3 m; quadratic terms absorb that curvature. Terms are
    [e, n, 1, e^2, e*n, n^2] (render.js evaluates the same polynomial). The
    residual is measured and returned so the build fails loudly if the fit
    is off.
    """
    (e0, n0, e1, n1) = extent_m
    ee, nn = np.meshgrid(np.linspace(e0, e1, 25), np.linspace(n0, n1, 25))
    ee, nn = ee.ravel(), nn.ravel()
    lon, lat = frame.to_wgs84(ee, nn)
    px, py = merc_px(lon, lat, z)
    u = (px - origin_px[0]) / size_px[0]
    v = 1.0 - (py - origin_px[1]) / size_px[1]  # three.js flips textures vertically
    A = np.column_stack([ee, nn, np.ones_like(ee), ee * ee, ee * nn, nn * nn])
    cu, *_ = np.linalg.lstsq(A, u, rcond=None)
    cv, *_ = np.linalg.lstsq(A, v, rcond=None)
    # Residual in meters: UV error * texture size * ground meters per mosaic px
    ground_m_per_px = (e1 - e0) / (np.ptp(px))
    res_px = np.hypot((A @ cu - u) * size_px[0], (A @ cv - v) * size_px[1])
    return cu.tolist(), cv.tolist(), float(res_px.max() * ground_m_per_px)


def rings_local(geom, frame):
    """Shapely (Multi)Polygon -> list of polygons, each [exterior, *holes] in local meters."""
    polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    out = []
    for p in polys:
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        rings = []
        for ring in [p.exterior, *p.interiors]:
            lon, lat = np.asarray(ring.coords).T[:2]
            e, n = frame.to_local(lon, lat)
            rings.append(np.round(np.column_stack([e, n])[:-1], 2).tolist())
        out.append(rings)
    return out


def mean_color(mosaic_arr, polys, to_px):
    """Average aerial color inside a footprint, used to tint its walls."""
    xs, ys = [], []
    for rings in polys:
        for x, y in rings[0]:
            px, py = to_px(x, y)
            xs.append(px)
            ys.append(py)
    bx0, by0 = max(int(min(xs)), 0), max(int(min(ys)), 0)
    bx1, by1 = min(int(max(xs)) + 1, mosaic_arr.shape[1]), min(int(max(ys)) + 1, mosaic_arr.shape[0])
    if bx1 <= bx0 or by1 <= by0:
        return None
    mask = Image.new("L", (bx1 - bx0, by1 - by0))
    d = ImageDraw.Draw(mask)
    for rings in polys:
        d.polygon([(px - bx0, py - by0) for px, py in (to_px(x, y) for x, y in rings[0])], fill=255)
        for hole in rings[1:]:
            d.polygon([(px - bx0, py - by0) for px, py in (to_px(x, y) for x, y in hole)], fill=0)
    m = np.asarray(mask) > 0
    if not m.any():
        return None
    return np.round(mosaic_arr[by0:by1, bx0:bx1][m].mean(axis=0)).astype(int).tolist()


def wall_color(roof_rgb, height_m, tint):
    """Wall color for one building.

    The aerial shows roofs, not façades, and Philadelphia's flat roofs are
    mostly grey and white, so walls tinted from the roof alone render the
    whole city beige. The city publishes no façade-material data. As a
    stylistic stand-in, low buildings (Old City's brick rowhouses and
    warehouses) are blended toward a brick color and taller ones keep their
    roof color. This is an assumption about appearance, not data: some low
    buildings are stone, stucco or glass. Set "wall_tint" to null in the
    config to turn it off.
    """
    if not tint or height_m > tint["max_height_m"]:
        return roof_rgb
    k = tint["mix"]
    return [round(r * (1 - k) + b * k) for r, b in zip(roof_rgb, tint["color"])]


def tree_radius_m(dbh_in):
    """Stylized canopy radius from trunk diameter at breast height (inches).

    A rough urban rule of thumb (crown spread grows ~0.3 m per inch of DBH,
    i.e. radius ~0.15 m per inch), clamped to keep young and missing-DBH trees
    visible and giant ones from swallowing a block. This is for looks only,
    not a measurement.
    """
    if not dbh_in or dbh_in <= 0:
        return 2.5
    return float(min(max(1.0 + 0.15 * dbh_in, 1.5), 7.0))


def main():
    cfg = load_config()
    name = cfg["name"]
    frame, cam, frames = area_setup(cfg)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    # --- ground texture ---------------------------------------------------
    mosaic, origin_px, z = build_mosaic(cfg)
    full_size = mosaic.size
    mosaic_arr = np.asarray(mosaic)
    to_px_full = lambda e, n: merc_px(*frame.to_wgs84(e, n), z)  # noqa: E731

    def to_mosaic_px(e, n):
        x, y = to_px_full(e, n)
        return float(x - origin_px[0]), float(y - origin_px[1])

    # Extent of the mosaic in local meters (its corners)
    corner_lon = [origin_px[0], origin_px[0] + full_size[0]]
    corner_lat = [origin_px[1], origin_px[1] + full_size[1]]
    scale = TILE * 2**z
    lons = [x / scale * 360.0 - 180.0 for x in corner_lon]
    lats = [math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale)))) for y in corner_lat]
    ce, cn = frame.to_local([lons[0], lons[1], lons[1], lons[0]], [lats[0], lats[0], lats[1], lats[1]])
    extent_m = (float(min(ce)), float(min(cn)), float(max(ce)), float(max(cn)))

    cu, cv, residual_m = fit_uv_poly(frame, origin_px, z, full_size, extent_m)
    if residual_m > 0.05:
        raise RuntimeError(f"ground texture UV fit is off by {residual_m:.3f} m (limit 0.05 m)")

    ground = mosaic
    if max(full_size) > MAX_TEXTURE_PX:
        f = MAX_TEXTURE_PX / max(full_size)
        ground = mosaic.resize((round(full_size[0] * f), round(full_size[1] * f)), Image.LANCZOS)
    # Optional simplification of the aerial before it goes on the ground and
    # roofs. Gemini copies photo clutter (cars, rooftop units, gravel) instead
    # of redrawing it; a small median filter removes that clutter while
    # keeping roof outlines, streets and shadows. See CHANGELOG (v3).
    median_px = (cfg.get("ground_filter") or {}).get("median_px")
    if median_px:
        ground = ground.filter(ImageFilter.MedianFilter(median_px))
    ground_path = PROCESSED / f"{name}_ground.jpg"
    ground.save(ground_path, quality=92)

    # --- buildings --------------------------------------------------------
    raw = json.loads((RAW / f"{name}_buildings.geojson").read_text())
    sources, outliers, dropped, buildings = Counter(), [], [], []
    for feat in raw["features"]:
        p = feat["properties"]
        try:
            geom = shape(feat["geometry"])
            if not geom.is_valid:
                geom = make_valid(geom)
        except Exception as exc:  # malformed geometry from the service
            dropped.append({"objectid": p.get("objectid"), "reason": str(exc)})
            continue
        polys = rings_local(geom, frame)
        if not polys:
            dropped.append({"objectid": p.get("objectid"), "reason": "no polygon area"})
            continue
        h, src, is_outlier = building_height(
            p.get("approx_hgt"),
            p.get("max_hgt"),
            cfg["default_building_height_m"],
            cfg["height_outlier_ratio"],
        )
        sources[src] += 1
        if is_outlier:
            outliers.append(
                {
                    "objectid": p.get("objectid"),
                    "address": p.get("address"),
                    "approx_hgt_ft": p.get("approx_hgt"),
                    "max_hgt_ft": p.get("max_hgt"),
                }
            )
        roof = mean_color(mosaic_arr, polys, to_mosaic_px) or [150, 140, 130]
        buildings.append(
            {
                "id": p.get("objectid"),
                "h": round(h, 2),
                "color": wall_color(roof, h, cfg.get("wall_tint")),
                "polys": polys,
            }
        )

    # --- trees ------------------------------------------------------------
    raw_trees = json.loads((RAW / f"{name}_trees.geojson").read_text())
    tlon, tlat, tr = [], [], []
    for feat in raw_trees["features"]:
        if not feat.get("geometry"):
            continue
        lon, lat = feat["geometry"]["coordinates"][:2]
        tlon.append(lon)
        tlat.append(lat)
        tr.append(tree_radius_m(feat["properties"].get("tree_dbh")))
    te, tn = frame.to_local(tlon, tlat)
    trees = [[round(e, 2), round(n, 2), round(r, 2)] for e, n, r in zip(te, tn, tr)]

    # --- scene ------------------------------------------------------------
    mpp = cam.meters_per_pixel
    scene = {
        "name": name,
        "origin_wgs84": [frame.lon0, frame.lat0],
        "camera": cam.three_js_params(),
        "meters_per_pixel": mpp,
        "frame_px": cfg["camera"]["frame_px"],
        "frames": [{"name": f.name, "col": f.col, "row": f.row, **f.frustum(mpp)} for f in frames],
        "ground": {
            "image": f"data/processed/{ground_path.name}",
            "extent_m": extent_m,
            "uv_poly": {"u": cu, "v": cv},
        },
        "buildings": buildings,
        "trees": trees,
    }
    (PROCESSED / f"{name}_scene.json").write_text(json.dumps(scene, separators=(",", ":")))

    qa = {
        "buildings_downloaded": len(raw["features"]),
        "buildings_in_scene": len(buildings),
        "buildings_dropped": dropped,
        "height_source_counts": dict(sources),
        "height_outliers_max_gt_ratio_x_approx": outliers,
        "tallest_buildings_m": sorted(
            ({"id": b["id"], "h": b["h"]} for b in buildings), key=lambda b: -b["h"]
        )[:10],
        "trees_in_scene": len(trees),
        "ground_texture_px": list(ground.size),
        "ground_texture_source_px": list(full_size),
        "uv_fit_max_residual_m": residual_m,
        "ground_median_filter_px": median_px,
        "frames": len(frames),
    }
    (PROCESSED / f"{name}_qa.json").write_text(json.dumps(qa, indent=2) + "\n")
    print(json.dumps({k: v for k, v in qa.items() if not isinstance(v, list) or len(v) < 6}, indent=2))
    print(f"height outliers: {len(outliers)}; dropped: {len(dropped)}")


if __name__ == "__main__":
    main()
