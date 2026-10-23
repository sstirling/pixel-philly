"""Cut a finished map into a Deep Zoom (DZI) tile pyramid for the viewer.

Input:  output/<area>/postprocessed/<prompt>/<stage>/mosaic.png
Output: output/<area>/tiles/<version>/map.dzi + map_files/<level>/<col>_<row>.webp
        output/<area>/tiles/<version>/map.json  (size, lon/lat fit, credits)

- 512 px tiles, lossless WebP: pixel art bleeds color under lossy codecs.
- Lattice cells outside the area (clipped corners) are filled with a soft
  background color instead of black.
- Each version gets its own folder and is never overwritten (tiny.london's
  lesson: CDNs keep serving stale tiles that were overwritten in place).

Usage: PP_AREA=downtown uv run python scripts/16_build_tiles.py --prompt qwen_joint_light8 --version v1
Then:  uv run python -m http.server 8000   # from the repo root
       open http://localhost:8000/viewer/?area=downtown&v=v1
"""

import argparse
import json
import time
from datetime import date

import pyvips

# Shared with 10_repaint_water.py, which clears pixels without source imagery to it
from pixelphilly.nodata import BACKGROUND
from pixelphilly.projection import area_dir, area_setup, load_config
from pixelphilly.viewer_geo import fit_lonlat_to_px


def cell_mask(frames, size, width, height):
    """255 where a kept frame is, 0 in clipped lattice corners (1 px per
    frame, scaled up with nearest-neighbor)."""
    cols = max(f.col for f in frames) + 1
    rows = max(f.row for f in frames) + 1
    cells = bytearray(cols * rows)
    for f in frames:
        cells[f.row * cols + f.col] = 255
    mask = pyvips.Image.new_from_memory(bytes(cells), cols, rows, 1, "uchar").resize(size, kernel="nearest")
    return mask.crop(0, 0, width, height)


def nodata_layer_mask(cfg, frames, size, width, height):
    """255 where source imagery exists, 0 where the city has none (no
    dilation: in the photo layer this marks missing data, it doesn't hide
    invented content)."""
    import numpy as np
    from PIL import Image, ImageDraw

    from pixelphilly.nodata import nodata_geometry
    from pixelphilly.projection import area_setup as _setup

    frame, cam, _ = _setup(cfg)
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    geom = nodata_geometry(cfg, frame, cam, x_origin, y_origin)
    img = Image.new("L", (width, height), 255)
    if not geom.is_empty:
        d = ImageDraw.Draw(img)
        for poly in [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", [])):
            if poly.geom_type == "Polygon" and not poly.is_empty:
                d.polygon(list(poly.exterior.coords), fill=0)
                for hole in poly.interiors:
                    d.polygon(list(hole.coords), fill=255)
    arr = np.asarray(img)
    return pyvips.Image.new_from_memory(arr.tobytes(), width, height, 1, "uchar")


def build_layer(img, mask, out, stem, suffix):
    bg = img.new_from_image(list(BACKGROUND)).cast("uchar")
    t0 = time.time()
    mask.ifthenelse(img, bg).dzsave(str(out / stem), tile_size=512, overlap=0, layout="dz", suffix=suffix)
    files = list((out / f"{stem}_files").rglob("*.webp"))
    print(f"{stem}: {len(files)} tiles, {sum(f.stat().st_size for f in files) / 1e6:.0f} MB, "
          f"{(time.time() - t0) / 60:.1f} min")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="qwen_joint_light8")
    ap.add_argument("--stage", default="water")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--with-photo", action="store_true",
                    help="also cut the render (2024 aerials on 3D buildings) as a second, aligned layer")
    args = ap.parse_args()

    cfg = load_config()
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    src = area_dir(cfg, "postprocessed", args.prompt, args.stage, "mosaic.png")
    out = area_dir(cfg, "tiles", args.version)
    if (out / "map.dzi").exists():
        raise SystemExit(f"{out} already exists; versions are immutable, pick a new --version")
    out.mkdir(parents=True, exist_ok=True)

    img = pyvips.Image.new_from_file(str(src), access="sequential")
    cells = cell_mask(frames, size, img.width, img.height)
    # Pixel art: lossless, so colors don't bleed
    build_layer(img, cells, out, "map", ".webp[lossless]")

    layers = {"illustration": "map.dzi"}
    if args.with_photo:
        photo = pyvips.Image.new_from_file(str(area_dir(cfg, "renders", "mosaic.png")))
        mask = (cells & nodata_layer_mask(cfg, frames, size, photo.width, photo.height))
        # Photos tolerate lossy compression; ~4x smaller than lossless
        build_layer(photo, mask, out, "photo", ".webp[Q=82]")
        layers["photo"] = "photo.dzi"

    fit = fit_lonlat_to_px(cfg)
    meta = {
        "area": cfg["name"],
        "label": cfg["label"],
        "version": args.version,
        "dzi": "map.dzi",
        "layers": layers,
        "width": img.width,
        "height": img.height,
        "background": "#%02x%02x%02x" % BACKGROUND,
        "fit": fit,
        "source": f"{args.prompt}/{args.stage}",
        "built": date.today().isoformat(),
        "credits": ("AI-generated illustration (Qwen-Image-Edit-2511 with a style LoRA trained on Gemini "
                    "3 Pro Image outputs; internal prototype). Data: City of Philadelphia building footprints, "
                    "2024 aerial imagery and PPR tree inventory; USGS NHD water."),
        "photo_credits": ("Photo layer: City of Philadelphia 2024 3-inch aerial imagery draped over L&I building "
                          "footprints extruded to LiDAR heights, rendered with the same camera as the "
                          "illustration. Building walls are untextured; tree shapes are stylized."),
    }
    (out / "map.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
