"""Turn the raw downloads into scene files the three.js renderer can load.

Small areas get one scene:
  data/processed/<name>_ground.jpg   aerial mosaic used as the ground texture
  data/processed/<name>_scene.json   buildings, trees, camera and frame lattice
Areas whose aerial would exceed the GPU texture limit set "render_tile_frames"
and get one scene per N x N-frame render tile (see main_tiled):
  data/processed/<name>/tiles/t_CC_RR.json, t_CC_RR_ground.jpg
  data/processed/<name>_tiles.json   index of tiles and the frames in each
Either way:
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

from pixelphilly.heights import FT_TO_M, building_height
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.sources import RAW

PROCESSED = REPO_ROOT / "data" / "processed"
TILE = 256
# Chromium's WebGL texture limit is 16384 px on Apple silicon and most
# desktop GPUs (render.js refuses to run if the texture is over the limit).
# At z19 the Old City mosaic is ~12,800 px, so it loads at full resolution.
MAX_TEXTURE_PX = 16384


def ground_texture(mosaic: Image.Image) -> Image.Image:
    """The mosaic is used at full resolution or not at all. A texture over the
    GPU limit used to be quietly downsampled here, which lowered ground detail
    without any warning; areas larger than the limit must be split into
    smaller render tiles instead (see the city-scale plan)."""
    if max(mosaic.size) > MAX_TEXTURE_PX:
        raise ValueError(
            f"ground texture {mosaic.size} exceeds the {MAX_TEXTURE_PX} px GPU limit; "
            "use a smaller area or per-tile scenes"
        )
    return mosaic


def merc_px(lon, lat, z):
    """WGS84 -> global Web Mercator pixel coordinates at zoom z."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    scale = TILE * 2**z
    x = (lon + 180.0) / 360.0 * scale
    r = np.radians(lat)
    y = (1.0 - np.log(np.tan(r) + 1.0 / np.cos(r)) / math.pi) / 2.0 * scale
    return x, y


def build_mosaic(cfg, tile_range=None):
    """Paste cached z19 tiles into one image. tile_range = (x0, x1, y0, y1);
    by default the area's whole range from the manifest. For clipped areas,
    tiles outside the downloaded polygon don't exist and are filled with
    neutral grey (they lie outside every kept frame's view). Tiles the server
    has no imagery for (".none" markers) are grey too; the model invents
    content on that featureless grey, so 10_repaint_water.py clears those
    areas to the background color (src/pixelphilly/nodata.py)."""
    z = cfg["imagery_zoom"]
    if tile_range is None:
        manifest = json.loads((RAW / "MANIFEST.json").read_text())
        info = manifest[f"imagery/{cfg['name']}/CityImagery_2024_3in/{z}"]
        (x0, x1), (y0, y1) = info["tile_x_range"], info["tile_y_range"]
    else:
        x0, x1, y0, y1 = tile_range
    tile_dir = RAW / "imagery" / "CityImagery_2024_3in" / str(z)
    w, h = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE
    mosaic = Image.new("RGB", (w, h), (128, 128, 128) if cfg.get("clip_frames_to_area") else (0, 0, 0))
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            path = tile_dir / f"{ty}_{tx}.jpg"
            if not path.exists() and cfg.get("clip_frames_to_area"):
                continue
            with Image.open(path) as t:
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


def prepare_ground(cfg, frame, tile_range=None):
    """Mosaic, its extent in local meters, the quadratic UV fit, and the
    (optionally median-filtered) texture that goes on the ground and roofs."""
    mosaic, origin_px, z = build_mosaic(cfg, tile_range)
    full_size = mosaic.size

    def to_mosaic_px(e, n):
        x, y = merc_px(*frame.to_wgs84(e, n), z)
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

    ground = ground_texture(mosaic)
    # Optional simplification of the aerial before it goes on the ground and
    # roofs. Gemini copies photo clutter (cars, rooftop units, gravel) instead
    # of redrawing it; a small median filter removes that clutter while
    # keeping roof outlines, streets and shadows. See CHANGELOG (v3).
    median_px = (cfg.get("ground_filter") or {}).get("median_px")
    if median_px:
        ground = ground.filter(ImageFilter.MedianFilter(median_px))
    return {"mosaic_arr": np.asarray(mosaic), "to_px": to_mosaic_px, "extent_m": extent_m,
            "uv": (cu, cv), "residual_m": residual_m, "ground": ground, "source_px": full_size,
            "median_px": median_px}


def load_buildings(cfg, frame):
    """Footprints in local meters with heights, plus QA bookkeeping. Roof
    colors are added later, from whichever ground mosaic covers them."""
    raw = json.loads((RAW / f"{cfg['name']}_buildings.geojson").read_text())
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
        # The highest City height on record caps LiDAR shapes (noise filter);
        # not written to the scene, which keeps only id/h/color/polys
        city = [v for v in (p.get("approx_hgt"), p.get("max_hgt")) if v and v > 0]
        ceiling = max(city) * FT_TO_M if city else None
        # approx_hgt alone is the typical height: stray returns don't move it
        # (max_hgt is the highest return), so it can vouch for a small LiDAR
        # region at that height; also not written to the scene
        approx = p.get("approx_hgt")
        typical = approx * FT_TO_M if approx and approx > 0 else None
        buildings.append({"id": p.get("objectid"), "h": round(h, 2), "polys": polys, "ceiling_m": ceiling,
                          "typical_m": typical})
    return buildings, {"downloaded": len(raw["features"]), "sources": sources,
                       "outliers": outliers, "dropped": dropped}


def lidar_shaped(cfg, frame, buildings):
    """Replace buildings inside the LiDAR region with stepped parts
    (pixelphilly.lidar). Each part keeps the building id with a suffix and is
    colored from the aerial under it, so a dark tower top and a light base
    stay distinct. Buildings outside the region, or without LiDAR coverage,
    keep their single height. The height grid is cached per area."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from pixelphilly import lidar

    name = cfg["name"]
    _, region = lidar.lidar_region_local(cfg)
    cache = PROCESSED / f"{name}_lidar_grid.npz"
    if cache.exists():
        z = np.load(cache)
        dsm, ground, origin = z["dsm"], z["ground"], tuple(z["origin"])
    else:
        tiles = (RAW / "lidar" / f"{name}_tiles.txt").read_text().split()
        dsm, ground, origin = lidar.dsm_from_las([RAW / "lidar" / t for t in tiles], frame, region.bounds, lidar.RES_M)
        np.savez_compressed(cache, dsm=dsm, ground=ground, origin=np.array(origin))
    import time

    out, shaped, fallback, n_parts = [], 0, 0, 0
    t0 = time.monotonic()
    for i, b in enumerate(buildings):
        if i and i % 5000 == 0:  # downtown has ~70,000 footprints
            print(f"  lidar shapes: {i:,}/{len(buildings):,} footprints, {time.monotonic() - t0:.0f} s", flush=True)
        fp = unary_union([Polygon(p[0], p[1:]) for p in b["polys"]]).buffer(0)
        if fp.is_empty or not region.contains(fp.centroid):
            out.append(b)
            continue
        base = lidar.footprint_base(fp, ground, origin, lidar.RES_M)
        parts = None if base is None else lidar.building_parts(fp, dsm, origin, lidar.RES_M, base=base,
                                                                ceiling=b.get("ceiling_m"),
                                                                typical=b.get("typical_m"))
        if not parts:
            out.append(b)
            fallback += 1
            continue
        shaped += 1
        for k, part in enumerate(parts):
            out.append({"id": f"{b['id']}-{k}", "h": part["h"], "polys": part["polys"]})
            n_parts += 1
    print(f"  lidar shapes: {shaped:,} shaped into {n_parts:,} parts in {time.monotonic() - t0:.0f} s", flush=True)
    return out, {"lidar_buildings_shaped": shaped, "lidar_fallback_single_height": fallback,
                 "lidar_parts": n_parts, "lidar_margin_m": lidar.LIDAR_MARGIN_M}


def colored(buildings, ground, cfg, cache=None):
    """Attach wall colors from the ground mosaic. With a cache (tiled areas),
    each building is colored once, so it looks the same in every tile."""
    out = []
    for b in buildings:
        if cache is not None and b["id"] in cache:
            color = cache[b["id"]]
        else:
            roof = mean_color(ground["mosaic_arr"], b["polys"], ground["to_px"]) or [150, 140, 130]
            color = wall_color(roof, b["h"], cfg.get("wall_tint"))
            if cache is not None:
                cache[b["id"]] = color
        out.append({"id": b["id"], "h": b["h"], "color": color, "polys": b["polys"]})
    return out


def load_trees(cfg, frame):
    raw_trees = json.loads((RAW / f"{cfg['name']}_trees.geojson").read_text())
    tlon, tlat, tr = [], [], []
    for feat in raw_trees["features"]:
        if not feat.get("geometry"):
            continue
        lon, lat = feat["geometry"]["coordinates"][:2]
        tlon.append(lon)
        tlat.append(lat)
        tr.append(tree_radius_m(feat["properties"].get("tree_dbh")))
    te, tn = frame.to_local(tlon, tlat)
    return [[round(e, 2), round(n, 2), round(r, 2)] for e, n, r in zip(te, tn, tr)]


def camera_params(cfg, cam):
    """Camera placement for three.js. The camera sits `camera_distance_m`
    back along the view direction with a far plane at twice that. 3 km is
    plenty for a 1 km neighborhood, but a 7 km area needs more: at 3 km the
    far edge of downtown fell past the far plane and was cut off."""
    return cam.three_js_params(cfg.get("camera_distance_m", 3000.0))


def scene_dict(cfg, frame, cam, frames, ground, ground_rel, buildings, trees):
    mpp = cam.meters_per_pixel
    cu, cv = ground["uv"]
    return {
        "name": cfg["name"],
        "origin_wgs84": [frame.lon0, frame.lat0],
        "camera": camera_params(cfg, cam),
        "meters_per_pixel": mpp,
        "frame_px": cfg["camera"]["frame_px"],
        "frames": [{"name": f.name, "col": f.col, "row": f.row, **f.frustum(mpp)} for f in frames],
        "ground": {
            "image": ground_rel,
            "extent_m": ground["extent_m"],
            "uv_poly": {"u": cu, "v": cv},
        },
        "buildings": buildings,
        "trees": trees,
    }


def write_qa(cfg, info, buildings_count, tallest, trees_count, extra):
    qa = {
        "buildings_downloaded": info["downloaded"],
        "buildings_in_scene": buildings_count,
        "buildings_dropped": info["dropped"],
        "height_source_counts": dict(info["sources"]),
        "height_outliers_max_gt_ratio_x_approx": info["outliers"],
        "tallest_buildings_m": tallest,
        "trees_in_scene": trees_count,
        **extra,
    }
    (PROCESSED / f"{cfg['name']}_qa.json").write_text(json.dumps(qa, indent=2) + "\n")
    print(json.dumps({k: v for k, v in qa.items() if not isinstance(v, list) or len(v) < 6}, indent=2))
    print(f"height outliers: {len(info['outliers'])}; dropped: {len(info['dropped'])}")


def main_single(cfg, frame, cam, frames):
    """One scene for the whole area (areas whose mosaic fits the GPU)."""
    name = cfg["name"]
    ground = prepare_ground(cfg, frame)
    ground_path = PROCESSED / f"{name}_ground.jpg"
    ground["ground"].save(ground_path, quality=92)
    buildings, info = load_buildings(cfg, frame)
    lidar_qa = {}
    if cfg.get("building_shapes") == "lidar":
        buildings, lidar_qa = lidar_shaped(cfg, frame, buildings)
    buildings = colored(buildings, ground, cfg)
    trees = load_trees(cfg, frame)
    scene = scene_dict(cfg, frame, cam, frames, ground, f"data/processed/{ground_path.name}", buildings, trees)
    (PROCESSED / f"{name}_scene.json").write_text(json.dumps(scene, separators=(",", ":")))
    tallest = sorted(({"id": b["id"], "h": b["h"]} for b in buildings), key=lambda b: -b["h"])[:10]
    write_qa(cfg, info, len(buildings), tallest, len(trees), {
        "ground_texture_px": list(ground["ground"].size),
        "ground_texture_source_px": list(ground["source_px"]),
        "uv_fit_max_residual_m": ground["residual_m"],
        "ground_median_filter_px": ground["median_px"],
        "frames": len(frames),
        **lidar_qa,
    })


# Buildings up to this far outside a render tile's ground can still appear
# in its frames (a 360 m tower leans ~360 m up-screen at 45 degrees), so each
# tile's scene and ground mosaic include them.
TILE_REACH_M = 360.0


def main_tiled(cfg, frame, cam, frames):
    """One scene per render tile of N x N frames, each with its own ground
    mosaic small enough for the GPU and its own UV fit. Writes
    data/processed/<area>/tiles/t_CC_RR.json + _ground.jpg and an index at
    data/processed/<area>_tiles.json."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    name = cfg["name"]
    n_tile = cfg["render_tile_frames"]
    z = cfg["imagery_zoom"]
    out_dir = PROCESSED / name / "tiles"
    out_dir.mkdir(parents=True, exist_ok=True)

    buildings, info = load_buildings(cfg, frame)
    # Shape every footprint once, before tiling: render tiles overlap (each
    # reaches 360 m past its frames), so per-tile shaping would repeat work
    # and could split one building differently in two tiles
    lidar_qa = {}
    if cfg.get("building_shapes") == "lidar":
        buildings, lidar_qa = lidar_shaped(cfg, frame, buildings)
    trees = load_trees(cfg, frame)
    # Spatial indexes over footprints (by exterior bbox) and trees
    b_boxes = [box(*Polygon(b["polys"][0][0]).bounds) for b in buildings]
    b_tree = STRtree(b_boxes)
    t_pts = np.array([[t[0], t[1]] for t in trees]) if trees else np.zeros((0, 2))

    groups = {}
    for f in frames:
        groups.setdefault((f.col // n_tile, f.row // n_tile), []).append(f)

    color_cache, index, residuals, tex_sizes, in_scene = {}, [], [], [], set()
    for (tc, tr), tile_frames in sorted(groups.items()):
        quads = []
        for f in tile_frames:
            e, n = cam.screen_to_ground([f.x0, f.x0 + f.size, f.x0 + f.size, f.x0],
                                        [f.y0, f.y0, f.y0 + f.size, f.y0 + f.size], 0.0)
            quads.append(Polygon(zip(e, n)))
        reach = unary_union(quads).buffer(TILE_REACH_M)
        # z19 tile range covering the reach region
        lon, lat = frame.to_wgs84(*np.asarray(reach.exterior.coords).T)
        px, py = merc_px(lon, lat, z)
        tile_range = (int(px.min() // TILE), int(px.max() // TILE), int(py.min() // TILE), int(py.max() // TILE))
        ground = prepare_ground(cfg, frame, tile_range)
        tex_sizes.append(max(ground["ground"].size))
        residuals.append(ground["residual_m"])
        stem = f"t_{tc:02d}_{tr:02d}"
        ground["ground"].save(out_dir / f"{stem}_ground.jpg", quality=92)

        idx = b_tree.query(reach)
        tile_b = colored([buildings[i] for i in sorted(idx)], ground, cfg, color_cache)
        in_scene.update(b["id"] for b in tile_b)
        xmin, ymin, xmax, ymax = reach.bounds
        sel = (t_pts[:, 0] >= xmin) & (t_pts[:, 0] <= xmax) & (t_pts[:, 1] >= ymin) & (t_pts[:, 1] <= ymax)
        tile_t = [trees[i] for i in np.nonzero(sel)[0]]

        scene = scene_dict(cfg, frame, cam, tile_frames, ground,
                           f"data/processed/{name}/tiles/{stem}_ground.jpg", tile_b, tile_t)
        (out_dir / f"{stem}.json").write_text(json.dumps(scene, separators=(",", ":")))
        index.append({"tile": stem, "scene": f"data/processed/{name}/tiles/{stem}.json",
                      "frames": [f.name for f in tile_frames], "buildings": len(tile_b), "trees": len(tile_t),
                      "texture_px": list(ground["ground"].size)})
        print(f"{stem}: {len(tile_frames)} frames, {len(tile_b)} buildings, {len(tile_t)} trees, "
              f"texture {ground['ground'].size}")

    (PROCESSED / f"{name}_tiles.json").write_text(json.dumps(index, indent=2) + "\n")
    tallest = sorted(({"id": b["id"], "h": b["h"]} for b in buildings), key=lambda b: -b["h"])[:10]
    write_qa(cfg, info, len(in_scene), tallest, len(trees), {
        "render_tiles": len(index),
        "max_ground_texture_px": max(tex_sizes),
        "uv_fit_max_residual_m": max(residuals),
        "ground_median_filter_px": (cfg.get("ground_filter") or {}).get("median_px"),
        "frames": len(frames),
        **lidar_qa,
    })


def refresh_camera(cfg, cam):
    """Rewrite only the camera block of existing scene files (after a camera
    setting change), instead of rebuilding mosaics and buildings."""
    from pixelphilly.scenes import scene_paths

    for rel in scene_paths(cfg):
        path = REPO_ROOT / rel
        scene = json.loads(path.read_text())
        scene["camera"] = camera_params(cfg, cam)
        path.write_text(json.dumps(scene, separators=(",", ":")))
        print(f"camera updated: {rel}")


def main():
    import sys

    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    if "--camera-only" in sys.argv:
        refresh_camera(cfg, cam)
        return
    if cfg.get("render_tile_frames"):
        main_tiled(cfg, frame, cam, frames)
    else:
        main_single(cfg, frame, cam, frames)


if __name__ == "__main__":
    main()
