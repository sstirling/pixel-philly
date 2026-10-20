"""Repaint open water in the stitched AI redraws with one consistent style.

Gemini picks its own river color in every frame (blue, brown, olive, tan),
which leaves the Delaware as a patchwork, and it sometimes invents objects on
open water. tiny.london fixed the same problems with a water check against
OpenStreetMap and a local repair. This does the deterministic equivalent on
the whole mosaic; the rules and style are in src/pixelphilly/waterpaint.py.

Writes output/postprocessed/<prompt>/water/<frame>.png, mosaic.png,
water_mask.png and report.json (including the render's water color model,
which 13_build_trainset.py reuses for training targets), and prints seam
ratios before and after.

Usage: uv run python scripts/10_repaint_water.py --prompt redraw_v3
"""

import argparse
import json

import numpy as np
from PIL import Image

from pixelphilly import waterpaint
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio


def load_mosaic(frames, size, folder, cols, rows, mode="RGB"):
    m = Image.new(mode, (cols * size, rows * size))
    for f in frames:
        m.paste(Image.open(folder / f"{f.name}.png").convert(mode), (f.col * size, f.row * size))
    return m


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

    redraw_dir = area_dir(cfg, "redraws", args.prompt)
    out_dir = area_dir(cfg, "postprocessed", args.prompt, "water")
    out_dir.mkdir(parents=True, exist_ok=True)

    redraw = np.asarray(load_mosaic(frames, size, redraw_dir, cols, rows)).copy()
    render = np.asarray(Image.open(area_dir(cfg, "renders", "mosaic.png")).convert("RGB"))
    buildings = waterpaint.grow(np.asarray(load_mosaic(frames, size, area_dir(cfg, "masks"), cols, rows, "L")) > 127)

    nhd_geom = waterpaint.nhd_geometry(cfg, frame, cam, x_origin, y_origin)
    nhd = waterpaint.rasterize_view(nhd_geom, 0, 0, 1.0, W, H)
    median, threshold = waterpaint.color_model(render, nhd, buildings)
    water = waterpaint.water_mask(render, nhd, buildings, median, threshold)

    before = seam_ratio(redraw, size)
    out = waterpaint.apply(redraw, water)
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
