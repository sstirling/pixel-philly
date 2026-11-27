"""Pixel-scale test: does drawing at a finer meters per pixel add detail?

Compares, for one spot, the era pilot's Phase C drawing at 0.293 m/px
(`atlas_<spot>_ea`, run `qwen_joint_light8_eraC`) with the same settings at
0.2 m/px (`atlas_<spot>_px20`, run `qwen_joint_light8_px20`) and 0.1465 m/px
(`atlas_<spot>_px15`, run `qwen_joint_light8_px15`). Variants whose drawings
don't exist yet are skipped. All configs share bbox, origin and camera angle,
so a ground point (e, n) can be placed in every mosaic through each config's
camera.

Writes, under output/scale_test/:
  <spot>_sheet.png  rows of same-ground crops, one column per scale, coarse
                    to fine. Every crop covers the same ground (about 59 m
                    across) and is shown at 400 px, nearest neighbor, so the
                    pixel size difference stays visible.
  <spot>_quality.json  the 47_era_compare quality measures for both drawings
                    (seam ratio, flat share, invented color, registration
                    shift, invented-water blobs).

Crops show buildings only, never addresses (same rule as the blind review).

Usage: uv run python scripts/48_scale_test.py --spot mayfair -- 128,297 0,0 -120,-80
       (points are local meters east, north of the scene origin)
"""

import argparse
import json

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, IsoCamera

ec = None  # 47_era_compare, loaded in main() so --help stays fast
SHOW_PX = 400
CROP_M = SHOW_PX * 0.1465  # ground width of every crop
VARIANTS = [("ea", "qwen_joint_light8_eraC", "renders_eraC"),
            ("px20", "qwen_joint_light8_px20", "renders"),
            ("px15", "qwen_joint_light8_px15", "renders")]
OUT = REPO_ROOT / "output" / "scale_test"


def _cfg(name):
    return json.loads((REPO_ROOT / "config" / f"{name}.json").read_text())


def placer(cfg):
    """(e, n, h) in local meters -> pixel in the config's full mosaic. Same
    origin arithmetic as 47_era_compare.review_items."""
    cam = IsoCamera.from_config(cfg)
    _, _, frames = ec.area_setup(cfg)
    s = cfg["camera"]["frame_px"]
    ox, oy = frames[0].x0 - frames[0].col * s, frames[0].y0 - frames[0].row * s

    def place(e, n, h=5.0):
        sx, sy = cam.world_to_screen(e, n, h)
        return float(sx) - ox, float(sy) - oy
    return place


def quality(spot, style):
    from pixelphilly.qa import flat_share, registration_shift
    from pixelphilly.trainset_clean import invented_color_share

    out = {}
    for suffix, run, rdir in available(spot, style):
        name = f"atlas_{spot}_{suffix}"
        cfg = _cfg(name)
        folder = style.drawn_dir(cfg, run)
        renders = REPO_ROOT / "output" / name / rdir
        _, _, frames = ec.area_setup(cfg)
        s = cfg["camera"]["frame_px"]
        img, have = style.mosaic(cfg, folder)
        flats, colors, shifts = [], [], []
        for f in frames:
            d = np.asarray(Image.open(folder / f"{f.name}.png").convert("RGB"))
            r = np.asarray(Image.open(renders / f"{f.name}.png").convert("RGB"))
            flats.append(flat_share(d))
            colors.append(invented_color_share(r, d))
            shifts.append(max(abs(x) for x in registration_shift(Image.fromarray(r), Image.fromarray(d))))
        water = None
        rep = folder / "report.json"
        if rep.exists():
            iw = json.loads(rep.read_text()).get("invented_water")
            if iw:
                water = sum(1 for b in iw["blobs"] if not b["exempt"])
        out[name] = {"run": run, "meters_per_pixel": cfg["camera"]["meters_per_pixel"], "frames": len(frames),
                     "seam": round(style.border_seam(img, have, s), 3), "flat": round(float(np.mean(flats)), 3),
                     "invented_color_pct": round(100 * float(np.mean(colors)), 2),
                     "max_shift_px": int(max(shifts)), "invented_water_blobs": water}
    return out


def available(spot, style):
    out = []
    for suffix, run, rdir in VARIANTS:
        name = f"atlas_{spot}_{suffix}"
        if (REPO_ROOT / "config" / f"{name}.json").exists() and style.drawn_dir(_cfg(name), run).exists():
            out.append((suffix, run, rdir))
    return out


def sheet(spot, style, points):
    cols = []
    for suffix, run, _ in available(spot, style):
        cfg = _cfg(f"atlas_{spot}_{suffix}")
        img, _ = style.mosaic(cfg, style.drawn_dir(cfg, run))
        cols.append((img, placer(cfg), CROP_M / cfg["camera"]["meters_per_pixel"]))
    w = SHOW_PX
    out = Image.new("RGB", (len(cols) * (w + 10) - 10, len(points) * (w + 10) - 10), "white")
    for i, (e, n) in enumerate(points):
        for j, (img, place, size) in enumerate(cols):
            x, y = place(e, n)
            crop = img.crop((round(x - size / 2), round(y - size / 2), round(x + size / 2), round(y + size / 2)))
            out.paste(crop.resize((w, w), Image.NEAREST), (j * (w + 10), i * (w + 10)))
    return out


def main():
    global ec
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", required=True, choices=["mayfair", "indhall"])
    ap.add_argument("points", nargs="+", help="e,n pairs in local meters (put -- before them: they can start with -)")
    args = ap.parse_args()
    import importlib.util

    spec = importlib.util.spec_from_file_location("era_compare", REPO_ROOT / "scripts" / "47_era_compare.py")
    ec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ec)
    style = ec._load_script("style_compare", "24_style_compare.py")
    OUT.mkdir(parents=True, exist_ok=True)
    pts = [tuple(float(v) for v in p.split(",")) for p in args.points]
    sheet(args.spot, style, pts).save(OUT / f"{args.spot}_sheet.png")
    q = quality(args.spot, style)
    (OUT / f"{args.spot}_quality.json").write_text(json.dumps(q, indent=2))
    print(json.dumps(q, indent=2))
    print("->", OUT)


if __name__ == "__main__":
    main()
