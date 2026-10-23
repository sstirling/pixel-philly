"""Repaint open water in the stitched AI redraws with one consistent style.

Gemini picks its own river color in every frame (blue, brown, olive, tan),
which leaves the Delaware as a patchwork, and it sometimes invents objects on
open water. tiny.london fixed the same problems with a water check against
OpenStreetMap and a local repair. This does the deterministic equivalent on
the whole mosaic; the rules and style are in src/pixelphilly/waterpaint.py.

It then clears everything where the city has no aerial imagery (the New
Jersey side of the river on the downtown map) to the viewer's background
color. The scene is flat grey there, and the model invents content on
featureless input; see src/pixelphilly/nodata.py.

Writes output/postprocessed/<prompt>/water/<frame>.png, mosaic.png,
water_mask.png and report.json (including the render's water color model,
which 13_build_trainset.py reuses for training targets), and prints seam
ratios before and after.

Usage: uv run python scripts/10_repaint_water.py --prompt redraw_v3
"""

import argparse
import json

import numpy as np
from PIL import Image, ImageFilter

from pixelphilly import nodata, waterpaint
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.qa import seam_ratio


def load_mosaic(frames, size, folder, cols, rows, mode="RGB"):
    m = Image.new(mode, (cols * size, rows * size))
    for f in frames:
        m.paste(Image.open(folder / f"{f.name}.png").convert(mode), (f.col * size, f.row * size))
    return m


HALO = 32  # px of neighboring frames read around each frame in the tiled path


class FrameReader:
    """Read any mosaic-coordinate rectangle from per-frame PNGs, without ever
    assembling the whole mosaic (a downtown mosaic is ~570 MP)."""

    def __init__(self, folder, frames, size, mode="RGB"):
        self.folder, self.size, self.mode = folder, size, mode
        self.by_cell = {(f.col, f.row): f for f in frames}
        self.cache = {}

    def frame(self, col, row):
        if (col, row) not in self.by_cell:
            return None
        if (col, row) not in self.cache:
            if len(self.cache) > 64:
                self.cache.clear()
            f = self.by_cell[(col, row)]
            self.cache[(col, row)] = np.asarray(Image.open(self.folder / f"{f.name}.png").convert(self.mode))
        return self.cache[(col, row)]

    def region(self, x0, y0, w, h):
        chans = 3 if self.mode == "RGB" else 1
        out = np.zeros((h, w, chans), np.uint8) if chans == 3 else np.zeros((h, w), np.uint8)
        s = self.size
        for row in range(y0 // s, (y0 + h - 1) // s + 1):
            for col in range(x0 // s, (x0 + w - 1) // s + 1):
                img = self.frame(col, row)
                if img is None:
                    continue
                fx0, fy0 = col * s, row * s
                ax, ay = max(x0, fx0), max(y0, fy0)
                bx, by = min(x0 + w, fx0 + s), min(y0 + h, fy0 + s)
                if ax < bx and ay < by:
                    out[ay - y0:by - y0, ax - x0:bx - x0] = img[ay - fy0:by - fy0, ax - fx0:bx - fx0]
        return out


def main_tiled(cfg, args, frame, cam, frames):
    """Frame-by-frame repaint for large areas. Each frame is processed with a
    HALO of its neighbors so shore bands and ripples continue across frame
    edges; the color model is sampled from all frames first."""
    size = cfg["camera"]["frame_px"]
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    out_dir = area_dir(cfg, "postprocessed", args.prompt, "water")
    out_dir.mkdir(parents=True, exist_ok=True)
    renders = FrameReader(area_dir(cfg, "renders"), frames, size)
    masks = FrameReader(area_dir(cfg, "masks"), frames, size, "L")
    redraws = FrameReader(area_dir(cfg, "redraws", args.prompt), frames, size)
    nhd_geom = waterpaint.nhd_geometry(cfg, frame, cam, x_origin, y_origin)
    nd_geom = nodata.nodata_geometry(cfg, frame, cam, x_origin, y_origin)

    # Color model of open water from the render, sampled across all frames
    samples = []
    for f in frames:
        gx, gy = f.col * size, f.row * size
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, 1.0, size, size)
        if nhd.sum() < 5000:
            continue
        core = np.asarray(Image.fromarray(nhd.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(31))) > 127
        b = waterpaint.grow(masks.frame(f.col, f.row) > 127)
        samples.append(renders.frame(f.col, f.row)[core & ~b][::7])
    sample = np.concatenate(samples).astype(int)
    median = np.median(sample, axis=0)
    typical = np.median(np.abs(sample - median).max(axis=1))
    threshold = max(30.0, 4.0 * float(typical))

    repainted = cleared = 0
    for f in frames:
        gx, gy = f.col * size - HALO, f.row * size - HALO
        span = size + 2 * HALO
        render = renders.region(gx, gy, span, span)
        bmask = waterpaint.grow(masks.region(gx, gy, span, span) > 127)
        nhd = waterpaint.rasterize_view(nhd_geom, gx, gy, 1.0, span, span)
        water = waterpaint.water_mask(render, nhd, bmask, median, threshold)
        out = waterpaint.apply(redraws.region(gx, gy, span, span).copy(), water, gx, gy, 1.0)
        if not nd_geom.is_empty:
            # Mask over the haloed region, so growth reaches in from neighbors
            nd = nodata.nodata_mask(nd_geom, gx, gy, span, span)
            out[nd] = nodata.BACKGROUND
            cleared += int(nd[HALO:HALO + size, HALO:HALO + size].sum())
        Image.fromarray(out[HALO:HALO + size, HALO:HALO + size]).save(out_dir / f"{f.name}.png")
        repainted += int(water[HALO:HALO + size, HALO:HALO + size].sum())

    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    mosaic = Image.new("RGB", (cols * size, rows * size))
    for f in frames:
        mosaic.paste(Image.open(out_dir / f"{f.name}.png"), (f.col * size, f.row * size))
    mosaic.save(out_dir / "mosaic.png")
    report = {"render_water_median_rgb": [round(v, 1) for v in median.tolist()],
              "color_threshold": round(float(threshold), 1), "water_px_repainted": repainted,
              "nodata_px_cleared": cleared, "mode": "per-frame with halo", "halo_px": HALO}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="redraw_v3")
    args = ap.parse_args()

    cfg = load_config()
    if cfg.get("render_tile_frames"):
        frame, cam, frames = area_setup(cfg)
        main_tiled(cfg, args, frame, cam, frames)
        return
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
    nd_geom = nodata.nodata_geometry(cfg, frame, cam, x_origin, y_origin)
    cleared = 0
    if not nd_geom.is_empty:
        nd = nodata.nodata_mask(nd_geom, 0, 0, W, H)
        out[nd] = nodata.BACKGROUND
        cleared = int(nd.sum())
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
        "nodata_px_cleared": cleared,
        "seam_ratio_before": round(before, 3),
        "seam_ratio_after": round(after, 3),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
