"""Turn AI redraws into true pixel art with a deterministic post-process.

Gemini draws a clean illustration but not a real pixel grid: its edges are
smooth and its colors drift from frame to frame. This step fixes both
without another model call:

1. Build ONE palette (median cut) from every redraw of a prompt version, so
   all frames share exactly the same colors. This also reduces color jumps
   where frames meet in the mosaic.
2. Downscale each frame by --scale (box filter, so each art pixel is the
   average of the image pixels it covers).
3. Snap every art pixel to the shared palette, with no dithering.
4. Upscale by the same factor with nearest-neighbor, so pixels stay square.

Runs after 10_repaint_water.py by default, so the repainted water colors
are part of the palette. Writes output/postprocessed/<prompt>/pixelized/
<frame>.png, mosaic.png and palette.png, and prints the seam ratio.

The palette depends on which frames exist when it is built; rerun after all
frames are redrawn so the final palette covers the whole area.

Usage: uv run python scripts/11_pixelize.py --prompt redraw_v3 [--scale 2 --colors 40]
       (--src redraws  pixelizes the raw redraws instead of the water-repainted ones)
"""

import argparse

import numpy as np
from PIL import Image

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.qa import seam_ratio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="redraw_v3")
    ap.add_argument("--src", default="water", choices=["water", "redraws"],
                    help="pixelize the water-repainted frames (default) or the raw redraws")
    ap.add_argument("--scale", type=int, default=2, help="image pixels per art pixel")
    ap.add_argument("--colors", type=int, default=40, help="shared palette size")
    args = ap.parse_args()

    if args.src == "water":
        src_dir = REPO_ROOT / "output" / "postprocessed" / args.prompt / "water"
    else:
        src_dir = REPO_ROOT / "output" / "redraws" / args.prompt
    out_dir = REPO_ROOT / "output" / "postprocessed" / args.prompt / "pixelized"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(src_dir.glob("frame_*.png"))
    if not paths:
        raise SystemExit(f"no redraws in {src_dir}")

    small = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        w, h = img.size
        small.append(img.resize((w // args.scale, h // args.scale), Image.BOX))

    # Palette from a montage of every downscaled frame, so it reflects the
    # whole area rather than whichever frame happens to come first.
    sw, sh = small[0].size
    montage = Image.new("RGB", (sw * len(small), sh))
    for i, s in enumerate(small):
        montage.paste(s, (i * sw, 0))
    palette = montage.quantize(colors=args.colors, method=Image.Quantize.MEDIANCUT)

    for p, s in zip(paths, small):
        q = s.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
        q.resize((sw * args.scale, sh * args.scale), Image.NEAREST).save(out_dir / p.name)

    # Swatch strip for the README / comparison page
    pal = palette.getpalette()[: args.colors * 3]
    swatch = Image.new("RGB", (args.colors, 1))
    swatch.putdata([tuple(pal[i : i + 3]) for i in range(0, len(pal), 3)])
    swatch.resize((args.colors * 16, 16), Image.NEAREST).save(out_dir / "palette.png")
    # Reassemble the mosaic and measure seams
    cfg = load_config()
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    have = {p.stem for p in paths}
    if all(f.name in have for f in frames):
        m = Image.new("RGB", (cols * size, rows * size))
        for f in frames:
            m.paste(Image.open(out_dir / f"{f.name}.png"), (f.col * size, f.row * size))
        m.save(out_dir / "mosaic.png")
        print(f"seam ratio: {seam_ratio(np.asarray(m), size):.3f}")
    print(f"{len(paths)} frames -> {out_dir} ({args.colors} colors, {args.scale}x pixels)")


if __name__ == "__main__":
    main()
