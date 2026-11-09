"""Before/after crops of every vessel group (config/vessels.json "groups").

Each side is a merged map version (output/philly/tiles/<v>/, the deepest DZI
level) or "areas": the vessel group's area's finished frames
(output/<area>/postprocessed/<run>/water/), for checks before a map is
built. Crops cover the group's box from the water up to 60 m, scaled by
--scale (2 = each map pixel becomes 2x2), side by side with labels, plus a
contact sheet of all groups.

    uv run python scripts/31_vessel_crops.py --before v14 --after areas --label step1 [--scale 1]
    uv run python scripts/31_vessel_crops.py --before v14 --after v15 --label v15 --scale 2
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pixelphilly.projection import area_setup, load_config  # noqa: E402

TS = 512
TOP_M = 60.0
PAD_PX = 60


class MapSource:
    def __init__(self, version, name="philly"):
        self.v = REPO_ROOT / "output" / name / "tiles" / version
        meta = json.loads((self.v / "map.json").read_text())
        self.ox, self.oy = meta["lattice_origin_px"]
        self.level = max(int(p.name) for p in (self.v / "map_files").iterdir() if p.name.isdigit())
        self.label = f"philly {version}"

    def crop(self, sx0, sy0, sx1, sy1, area=None):
        x0, y0, x1, y1 = int(sx0 - self.ox), int(sy0 - self.oy), int(sx1 - self.ox), int(sy1 - self.oy)
        out = Image.new("RGB", (x1 - x0, y1 - y0), (204, 214, 227))
        for ty in range(y0 // TS, (y1 - 1) // TS + 1):
            for tx in range(x0 // TS, (x1 - 1) // TS + 1):
                f = self.v / f"map_files/{self.level}/{tx}_{ty}.webp"
                if f.exists():
                    out.paste(Image.open(f).convert("RGB"), (tx * TS - x0, ty * TS - y0))
        return out


class AreaSource:
    def __init__(self, run):
        self.run = run
        self.label = f"area frames ({run}, repainted)"

    def crop(self, sx0, sy0, sx1, sy1, area):
        cfg = load_config(area)
        _, _, frames = area_setup(cfg)
        size = cfg["camera"]["frame_px"]
        out = Image.new("RGB", (int(sx1 - sx0), int(sy1 - sy0)), (204, 214, 227))
        d = REPO_ROOT / "output" / area / "postprocessed" / self.run / "water"
        for f in frames:
            if f.x0 + size < sx0 or f.x0 > sx1 or f.y0 + size < sy0 or f.y0 > sy1:
                continue
            p = d / f"{f.name}.png"
            if p.exists():
                out.paste(Image.open(p).convert("RGB"), (int(f.x0 - sx0), int(f.y0 - sy0)))
        return out


def screen_box(area, bbox):
    frame, cam, _ = area_setup(load_config(area))
    w, s, e, n = bbox
    lon = np.array([w, e, w, e]); lat = np.array([s, s, n, n])
    E, N = frame.to_local(lon, lat)
    xs, ys = [], []
    for h in (0.0, TOP_M):
        x, y = cam.world_to_screen(E, N, h)
        xs += list(x); ys += list(y)
    return min(xs) - PAD_PX, min(ys) - PAD_PX, max(xs) + PAD_PX, max(ys) + PAD_PX


def source(spec, run):
    return AreaSource(run) if spec == "areas" else MapSource(spec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--run", default="qwen_joint_light8_fac")
    args = ap.parse_args()
    cfg = json.loads((REPO_ROOT / "config" / "vessels.json").read_text())
    out_dir = REPO_ROOT / "output" / "review" / "vessels" / f"crops_{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    b, a = source(args.before, args.run), source(args.after, args.run)
    font = ImageFont.load_default(size=22)
    thumbs = []
    for gid, g in cfg["groups"].items():
        box = screen_box(g["area"], g["bbox"])
        imgs = [s.crop(*box, area=g["area"]) for s in (b, a)]
        if args.scale != 1:
            imgs = [im.resize((im.width * args.scale, im.height * args.scale), Image.NEAREST) for im in imgs]
        W, H = imgs[0].size
        sheet = Image.new("RGB", (2 * W + 20, H + 44), "white")
        d = ImageDraw.Draw(sheet)
        for i, (im, s) in enumerate(zip(imgs, (b, a))):
            sheet.paste(im, (i * (W + 20), 44))
        d.text((8, 10), f"{gid} {g['label']}: left {b.label}, right {a.label}, {args.scale}x. "
                        "pixel-philly AI-generated illustration", fill="black", font=font)
        p = out_dir / f"{gid}.jpg"
        sheet.save(p, quality=88)
        t = sheet.copy(); t.thumbnail((900, 500)); thumbs.append(t)
        print(p, sheet.size)
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    cs = Image.new("RGB", (cols * 900, rows * 500), "white")
    for i, t in enumerate(thumbs):
        cs.paste(t, ((i % cols) * 900, (i // cols) * 500))
    cs.save(out_dir / "contact_sheet.jpg", quality=85)
    print(out_dir / "contact_sheet.jpg")


if __name__ == "__main__":
    main()
