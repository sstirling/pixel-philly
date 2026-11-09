"""Crops of one place at three stages from an area's frames: the render
(model input), the raw drawing (before the water repaint) and the finished
drawing (after the repaint and invented-water fix), plus the repaint's
change mask. For diagnosing what changed a spot (Nov. 5: bridges).

    uv run python scripts/32_stage_crops.py --area south_lidar --lonlat -75.1817,39.9513 --name walnut \
        [--half-m 120] [--scale 2] [--out output/review/bridges/stages]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pixelphilly.projection import area_setup, load_config  # noqa: E402

RUN = "qwen_joint_light8_fac"


def stitch(area, folder, box):
    cfg = load_config(area)
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    x0, y0, x1, y1 = box
    out = Image.new("RGB", (x1 - x0, y1 - y0), (204, 214, 227))
    for f in frames:
        if f.x0 + size < x0 or f.x0 > x1 or f.y0 + size < y0 or f.y0 > y1:
            continue
        p = folder / f"{f.name}.png"
        if p.exists():
            out.paste(Image.open(p).convert("RGB"), (int(f.x0 - x0), int(f.y0 - y0)))
    return out


def box_for(area, lon, lat, half_m):
    cfg = load_config(area)
    frame, cam, _ = area_setup(cfg)
    e, n = frame.to_local(np.array([lon]), np.array([lat]))
    sx, sy = cam.world_to_screen(e, n, 0.0)
    half = int(half_m / cfg["camera"]["meters_per_pixel"])
    cx, cy = int(sx[0]), int(sy[0])
    return cx - half, cy - half, cx + half, cy + half


def crops(area, lon, lat, half_m=120.0):
    box = box_for(area, lon, lat, half_m)
    root = REPO_ROOT / "output" / area
    render = stitch(area, root / "renders", box)
    raw = stitch(area, root / "redraws" / RUN, box)
    done = stitch(area, root / "postprocessed" / RUN / "water", box)
    diff = (np.abs(np.asarray(raw, int) - np.asarray(done, int)).max(axis=2) > 12)
    over = np.asarray(raw).copy()
    over[diff] = (255, 0, 0)
    return {"render": render, "before repaint": raw, "after repaint": done, "changed by repaint (red)": Image.fromarray(over)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", required=True)
    ap.add_argument("--lonlat", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--half-m", type=float, default=120.0)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--out", default=str(REPO_ROOT / "output" / "review" / "bridges" / "stages"))
    args = ap.parse_args()
    lon, lat = map(float, args.lonlat.split(","))
    ims = crops(args.area, lon, lat, args.half_m)
    font = ImageFont.load_default(size=20)
    w, h = next(iter(ims.values())).size
    w, h = w * args.scale, h * args.scale
    sheet = Image.new("RGB", (4 * w + 30, h + 34), "white")
    d = ImageDraw.Draw(sheet)
    for i, (lab, im) in enumerate(ims.items()):
        sheet.paste(im.resize((w, h), Image.NEAREST), (i * (w + 10), 34))
        d.text((i * (w + 10) + 4, 6), f"{args.name}: {lab}", fill="black", font=font)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / f"{args.name}.jpg", quality=88)
    print(out / f"{args.name}.jpg", sheet.size)


if __name__ == "__main__":
    main()
