"""Render every frame of the lattice with headless Chromium.

Writes:

  output/renders/<frame>.png         1024 x 1024 render frames
  output/renders/mosaic.png          all frames pasted on the lattice
  output/renders/mosaic_preview.jpg  the mosaic at 1/4 size for a quick look

(--mode mask writes building silhouettes to output/masks/ instead.)

Usage: uv run python scripts/06_render.py [--mode mask] [--only frame_02_01]
"""

import argparse
import json

from PIL import Image

from pixelphilly.browser_render import Renderer
from pixelphilly.projection import REPO_ROOT, area_dir, load_config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="color", choices=["color", "mask"])
    ap.add_argument("--only", help="render just this frame name")
    args = ap.parse_args()

    cfg = load_config()
    scene_rel = f"data/processed/{cfg['name']}_scene.json"
    scene = json.loads((REPO_ROOT / scene_rel).read_text())
    size = scene["frame_px"]
    out_dir = area_dir(cfg, "renders" if args.mode == "color" else "masks")
    out_dir.mkdir(parents=True, exist_ok=True)

    images = {}
    with Renderer(scene_rel, size) as r:
        print("renderer:", r.info)
        for i, f in enumerate(scene["frames"]):
            if args.only and f["name"] != args.only:
                continue
            img = r.frame(i, args.mode)
            img.save(out_dir / f"{f['name']}.png")
            images[(f["col"], f["row"])] = img
            print(f"  {f['name']}")

    if args.only or args.mode != "color":
        return
    cols = max(c for c, _ in images) + 1
    rows = max(r for _, r in images) + 1
    mosaic = Image.new("RGB", (cols * size, rows * size))
    for (c, r), img in images.items():
        mosaic.paste(img, (c * size, r * size))
    mosaic.save(out_dir / "mosaic.png")
    mosaic.resize((mosaic.width // 4, mosaic.height // 4), Image.LANCZOS).save(
        out_dir / "mosaic_preview.jpg", quality=88
    )
    print(f"mosaic {mosaic.size} -> {out_dir / 'mosaic.png'}")


if __name__ == "__main__":
    main()
