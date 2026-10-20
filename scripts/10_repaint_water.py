"""Repaint open water in the AI redraws with one consistent water style.

Gemini picks its own river color in every frame (blue, brown, olive, tan),
which leaves the Delaware as a patchwork, and it sometimes invents objects on
open water. tiny.london fixed the same problems with a water check against
OpenStreetMap and a local repair. This does the deterministic equivalent:

A pixel is repainted only if all three hold:
  1. USGS NHD says it is water (both banks of the Delaware; 04b_fetch_water_nhd.py);
  2. the render shows open water there: its color is close to the river's
     median color in the render. This keeps the bridge deck and its shadow,
     piers and boats, which sit inside the NHD polygon but are not water;
  3. no building covers it (the silhouette masks from 06_render.py --mode mask).

The fill is drawn on the whole mosaic in global pixel coordinates, so its
pattern runs continuously across frame borders:
  - one base color for all water;
  - sparse short light dashes on a 2 px grid (pixel-art ripples), placed by a
    fixed hash of position so every run is identical;
  - a darker band along the shoreline.
The colors are a style choice (a muted blue-grey; the real Delaware is
brownish), set in WATER_STYLE below.

Writes output/postprocessed/<prompt>/water/<frame>.png, mosaic.png and
water_mask.png, and prints seam ratios before and after.

Usage: uv run python scripts/10_repaint_water.py --prompt redraw_v3
"""

import argparse
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import seam_ratio
from pixelphilly.sources import RAW

WATER_STYLE = {
    "base": (88, 124, 140),
    "ripple": (122, 158, 170),
    "shore": (66, 98, 114),
    "shore_px": 4,
    # One ripple dash starts on roughly 1 in this many 2x2 art pixels
    "ripple_rarity": 140,
    "ripple_len_art_px": 3,
}


def project_water(cfg, frame, cam, x_origin, y_origin, width, height):
    data = json.loads((RAW / f"{cfg['name']}_water_nhd.geojson").read_text())
    view = box(0, 0, width, height)
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
            polys.append(Polygon(rings[0], rings[1:]).buffer(0).intersection(view))
    return unary_union(polys)


def rasterize(geom, width, height):
    img = Image.new("L", (width, height))
    d = ImageDraw.Draw(img)
    for p in [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", [])):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        d.polygon(list(p.exterior.coords), fill=255)
        for hole in p.interiors:
            d.polygon(list(hole.coords), fill=0)
    return img


def load_mosaic(frames, size, folder, cols, rows, mode="RGB"):
    m = Image.new(mode, (cols * size, rows * size))
    for f in frames:
        m.paste(Image.open(folder / f"{f.name}.png").convert(mode), (f.col * size, f.row * size))
    return m


def ripple_mask(width, height, style):
    """Sparse horizontal dashes on a 2 px art grid, from a fixed position hash."""
    ay, ax = np.mgrid[0 : height // 2, 0 : width // 2]
    h = (ax * 73856093) ^ (ay * 19349663)
    starts = (h % style["ripple_rarity"]) == 0
    dash = np.zeros_like(starts)
    for k in range(style["ripple_len_art_px"]):
        dash |= np.roll(starts, k, axis=1)
    return np.kron(dash, np.ones((2, 2), bool))[:height, :width]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="redraw_v3")
    args = ap.parse_args()

    cfg = load_config()
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    x_origin = min(f.x0 for f in frames)
    y_origin = min(f.y0 for f in frames)
    W, H = cols * size, rows * size

    redraw_dir = REPO_ROOT / "output" / "redraws" / args.prompt
    out_dir = REPO_ROOT / "output" / "postprocessed" / args.prompt / "water"
    out_dir.mkdir(parents=True, exist_ok=True)

    redraw = np.asarray(load_mosaic(frames, size, redraw_dir, cols, rows)).copy()
    render = np.asarray(Image.open(REPO_ROOT / "output" / "renders" / "mosaic.png").convert("RGB")).astype(int)
    buildings = load_mosaic(frames, size, REPO_ROOT / "output" / "masks", cols, rows, "L")
    # Grow building silhouettes slightly so repaint never nibbles their edges
    buildings = np.asarray(buildings.filter(ImageFilter.MaxFilter(5))) > 127

    nhd_img = rasterize(project_water(cfg, frame, cam, x_origin, y_origin, W, H), W, H)
    nhd = np.asarray(nhd_img) > 127

    # Color model of open water from the render, sampled well inside the
    # NHD polygon and away from buildings
    core = np.asarray(nhd_img.filter(ImageFilter.MinFilter(31))) > 127
    sample = render[core & ~buildings]
    median = np.median(sample, axis=0)
    dist = np.abs(render - median).max(axis=2)
    typical = np.median(np.abs(sample - median).max(axis=1))
    threshold = max(30.0, 4.0 * typical)
    looks_wet = Image.fromarray(((dist < threshold) * 255).astype(np.uint8))
    # Median filter removes speckle in the color test without eating the
    # bridge or piers, which are far larger than the filter
    looks_wet = np.asarray(looks_wet.filter(ImageFilter.MedianFilter(9))) > 127

    water = nhd & looks_wet & ~buildings
    style = WATER_STYLE
    shore = water & ~(
        np.asarray(Image.fromarray(water.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(2 * style["shore_px"] + 1))) > 127
    )
    ripples = ripple_mask(W, H, style) & water & ~shore

    before = seam_ratio(redraw, size)
    out = redraw.copy()
    out[water] = style["base"]
    out[ripples] = style["ripple"]
    out[shore] = style["shore"]
    after = seam_ratio(out, size)

    Image.fromarray(out).save(out_dir / "mosaic.png")
    Image.fromarray((water * 255).astype(np.uint8)).save(out_dir / "water_mask.png")
    for f in frames:
        Image.fromarray(out[f.row * size : (f.row + 1) * size, f.col * size : (f.col + 1) * size]).save(
            out_dir / f"{f.name}.png"
        )

    report = {
        "render_water_median_rgb": [round(v, 1) for v in median.tolist()],
        "color_threshold": round(float(threshold), 1),
        "water_px_repainted": int(water.sum()),
        "nhd_px": int(nhd.sum()),
        "nhd_px_kept_not_water": int((nhd & ~water).sum()),
        "seam_ratio_before": round(before, 3),
        "seam_ratio_after": round(after, 3),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
