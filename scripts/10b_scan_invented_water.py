"""Dry run: find water the drawing model invented on land, write nothing in output/.

Scans each area's finished frames (output/<area>/postprocessed/<prompt>/water/,
else the redraws) with the same rules 10_repaint_water.py --invented-water fix
uses (pixelphilly.invented_water), and writes, to --out only:
  blobs.json        every blob: area, frame(s), bbox in mosaic px, exemption
  contact_sheet.png the --top largest flagged blobs: drawing | render | blob outline
  exempted_sheet.png the --top largest blobs exempted as wetland or missing roof (to check both directions)

Usage: uv run python scripts/10b_scan_invented_water.py --areas south_lidar,atlas_cityhall_fac \\
           --prompt qwen_joint_light8 --out /tmp/scan
"""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config

spec = importlib.util.spec_from_file_location("repaint", REPO_ROOT / "scripts" / "10_repaint_water.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


RENDERS = ["renders"]


def renders_dir(cfg, name):
    d = area_dir(cfg, name)
    return d if d.exists() else area_dir(cfg, "renders")


def sheet(blobs, path):
    """Contact sheet: per blob, drawing | render | drawing with the blob outlined."""
    tiles = []
    for b in blobs:
        cfg = load_config(b["area"])
        _, _, frames = area_setup(cfg)
        size = cfg["camera"]["frame_px"]
        x0, y0, x1, y1 = b["bbox"]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        half = max(80, (max(x1 - x0, y1 - y0) // 2) + 60)
        gx, gy = cx - half, cy - half
        src = REPO_ROOT / b["source"]
        d = rp.FrameReader(src, frames, size).region(gx, gy, 2 * half, 2 * half)
        r = rp.FrameReader(renders_dir(cfg, RENDERS[0]), frames, size).region(gx, gy, 2 * half, 2 * half)
        outline = Image.fromarray(d).copy()
        ImageDraw.Draw(outline).rectangle([x0 - gx, y0 - gy, x1 - gx, y1 - gy], outline=(255, 0, 255), width=3)
        row = Image.new("RGB", (3 * 260 + 20, 286), "white")
        for i, im in enumerate((Image.fromarray(d), Image.fromarray(r), outline)):
            row.paste(im.resize((260, 260)), (i * 270, 0))
        label = f"{b['area']} {','.join(b['frames'][:3])} {b['area_px']} px bbox {b['bbox']}"
        if b["exempt"]:
            label += f" EXEMPT: {b['exempt']}"
        ImageDraw.Draw(row).text((4, 266), label, fill=(0, 0, 0))
        tiles.append(row)
    if not tiles:
        return
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (cols * tiles[0].width + 20, rows * tiles[0].height), "white")
    for i, t in enumerate(tiles):
        img.paste(t, ((i % cols) * (tiles[0].width + 20), (i // cols) * tiles[0].height))
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", required=True)
    ap.add_argument("--prompt", default="qwen_joint_light8")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--renders", default="renders",
                    help="renders folder the drawings were made from (e.g. renders_v1 after a re-render), "
                    "used when it exists, else renders")
    ap.add_argument("--sheet-reasons", default="NWI wetland,roof-like (building missing)",
                    help="also draw a sheet of blobs exempted for these reasons (to check the exemptions)")
    args = ap.parse_args()
    RENDERS[0] = args.renders
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    allblobs = []
    for name in [a.strip() for a in args.areas.split(",")]:
        cfg = load_config(name)
        frame, cam, frames = area_setup(cfg)
        size = cfg["camera"]["frame_px"]
        post = area_dir(cfg, "postprocessed", args.prompt, "water")
        src = post if post.exists() else area_dir(cfg, "redraws", args.prompt)
        done = [f for f in frames if (src / f"{f.name}.png").exists()]
        x_origin = min(f.x0 - f.col * size for f in frames)
        y_origin = min(f.y0 - f.row * size for f in frames)
        water_geom, pools, wetlands = rp.invented_water_context(cfg, frame, cam, x_origin, y_origin)
        blobs, _ = rp.scan_invented_water(
            cfg, done, size, rp.FrameReader(src, done, size), rp.FrameReader(renders_dir(cfg, args.renders), frames, size),
            rp.FrameReader(area_dir(cfg, "masks"), frames, size, "L"), water_geom, pools, wetlands)
        flagged = [b for b in blobs if not b["exempt"]]
        reasons = {}
        for b in blobs:
            if b["exempt"]:
                reasons[b["exempt"]] = reasons.get(b["exempt"], 0) + 1
        print(f"{name}: {len(done)} frames from {src.relative_to(REPO_ROOT)}; {len(flagged)} flagged blobs "
              f"({sum(b['area_px'] for b in flagged):,} px); exempt {reasons or '-'}; pools {len(pools)}; "
              f"wetland polygons {'yes' if not wetlands.is_empty else 'none'}", flush=True)
        for b in blobs:
            allblobs.append({"area": name, "source": str(src.relative_to(REPO_ROOT)), **b})
    (out / "blobs.json").write_text(json.dumps(allblobs, indent=1))
    top = sorted([b for b in allblobs if not b["exempt"]], key=lambda b: -b["area_px"])[:args.top]
    sheet(top, out / "contact_sheet.png")
    reasons = {r.strip() for r in args.sheet_reasons.split(",") if r.strip()}
    sheet(sorted([b for b in allblobs if b["exempt"] in reasons], key=lambda b: -b["area_px"])[:args.top],
          out / "exempted_sheet.png")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
