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

One map from several areas drawn as regions (they must share a projection
origin and camera; pixelphilly.regions):
  uv run python scripts/16_build_tiles.py --areas south_lidar,north_lidar --name philly --version v1 \
      [--with-photo] [--dry-run]
  -> output/philly/tiles/v1/, viewer at ?area=philly&v=v1
The union sits on the global frame lattice; where two areas have a frame at
the same cell the FIRST listed wins (South first, so the known band keeps
South's drawn pixels), except cells a later region run re-repainted in
its water_band/ folder (pixelphilly.regions.cell_sources: an override
applies to cells owned by the area its report names; between two
overrides of one cell the later area listed wins). Frames are read one PNG per cell
(output/<area>/postprocessed/<prompt>/<stage>/<frame>.png; photo layer:
output/<area>/renders/<frame>.png) and joined by pyvips without loading the
~43k x 42k px union into memory. --dry-run reports the union and the fit
without reading any frame.
"""

import argparse
import json
import time
from datetime import date

import pyvips

# Shared with 10_repaint_water.py, which clears pixels without source imagery to it
from pixelphilly.nodata import BACKGROUND
from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config
from pixelphilly.regions import cell_sources
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
    ap.add_argument("--areas", help="comma-separated areas drawn as regions, merged into one map (first wins)")
    ap.add_argument("--name", help="--areas: the merged map's name (output/<name>/tiles/<version>/)")
    ap.add_argument("--label", help="--areas: the viewer title (default: the areas' labels)")
    ap.add_argument("--dry-run", action="store_true", help="--areas: report the union and fit, write nothing")
    args = ap.parse_args()
    if args.areas:
        if not args.name:
            ap.error("--areas needs --name")
        build_union(args)
        return

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
                    "2024 aerial imagery and PPR tree inventory; USGS NHD water.")
        + (" " + OSM_CREDIT if (REPO_ROOT / "data" / "raw" / f"{cfg['name']}_osm.json").exists() else ""),
        "photo_credits": ("Photo layer: City of Philadelphia 2024 3-inch aerial imagery draped over L&I building "
                          "footprints extruded to LiDAR heights, rendered with the same camera as the "
                          "illustration. Building walls are untextured; tree shapes are stylized."),
    }
    (out / "map.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"-> {out}")



CREDITS = ("AI-generated illustration (Qwen-Image-Edit-2511 with a style LoRA trained on Gemini "
           "3 Pro Image outputs; internal prototype). Data: City of Philadelphia building footprints, "
           "2024 aerial imagery and PPR tree inventory; USGS NHD water.")
PHOTO_CREDITS = ("Photo layer: City of Philadelphia 2024 3-inch aerial imagery draped over L&I building "
                 "footprints extruded to LiDAR heights, rendered with the same camera as the "
                 "illustration. Building walls are untextured; tree shapes are stylized.")
RAIL_CREDIT = "Rail: SEPTA; City of Philadelphia."
# ODbL attribution, for areas whose façade colours use OpenStreetMap (04g_fetch_osm.py)
OSM_CREDIT = "Façade colours in part © OpenStreetMap contributors (ODbL)."


def union_layer(u, size, path_of):
    """The union as one lazy pyvips image: one PNG per cell (path_of(area,
    frame)), black where no area has a frame (masked to the background
    later). Sequential access: dzsave walks top to bottom, so each PNG is
    decoded once."""
    blank = pyvips.Image.black(size, size, bands=3)
    tiles = []
    for r in range(u["rows"]):
        for c in range(u["cols"]):
            cell = u["cells"].get((c, r))
            if cell is None:
                tiles.append(blank)
                continue
            im = pyvips.Image.new_from_file(str(path_of(*cell)), access="sequential")
            tiles.append(im.flatten() if im.hasalpha() else im)
    return pyvips.Image.arrayjoin(tiles, across=u["cols"])


def union_mask(u, size, nodata=None):
    """255 on cells some area provides, 0 elsewhere; with nodata (shapely
    geometry in union pixels), also 0 where the source imagery is missing.
    Built cell by cell, so only cells that touch missing imagery are
    rasterized (the union is too big for one in-memory mask)."""
    import numpy as np
    from PIL import Image, ImageDraw
    from shapely.geometry import box

    off = pyvips.Image.black(size, size)
    on = (off + 255).cast("uchar")
    off = off.cast("uchar")
    tiles = []
    for r in range(u["rows"]):
        for c in range(u["cols"]):
            if (c, r) not in u["cells"]:
                tiles.append(off)
                continue
            cell = box(c * size, r * size, (c + 1) * size, (r + 1) * size)
            if nodata is None or nodata.is_empty or not nodata.intersects(cell):
                tiles.append(on)
                continue
            img = Image.new("L", (size, size), 255)
            d = ImageDraw.Draw(img)
            part = nodata.intersection(cell)
            for poly in [part] if part.geom_type == "Polygon" else list(getattr(part, "geoms", [])):
                if poly.geom_type == "Polygon" and not poly.is_empty:
                    d.polygon([(x - c * size, y - r * size) for x, y in poly.exterior.coords], fill=0)
                    for hole in poly.interiors:
                        d.polygon([(x - c * size, y - r * size) for x, y in hole.coords], fill=255)
            arr = np.asarray(img)
            tiles.append(pyvips.Image.new_from_memory(arr.tobytes(), size, size, 1, "uchar"))
    return pyvips.Image.arrayjoin(tiles, across=u["cols"])


def build_union(args):
    """One map from several areas drawn as regions (see the module docstring)."""
    from shapely.geometry import box
    from shapely.ops import unary_union

    from pixelphilly.nodata import nodata_geometry
    from pixelphilly.regions import check_same_space, union_lattice
    from pixelphilly.viewer_geo import fit_lonlat_to_px_union

    names = [a.strip() for a in args.areas.split(",") if a.strip()]
    cfgs = [load_config(n) for n in names]
    try:
        check_same_space(cfgs)
    except ValueError as e:
        raise SystemExit(str(e))
    setups = {c["name"]: area_setup(c) for c in cfgs}
    u = union_lattice([(c["name"], setups[c["name"]][2]) for c in cfgs])
    size = cfgs[0]["camera"]["frame_px"]
    width, height = u["cols"] * size, u["rows"] * size
    fit = fit_lonlat_to_px_union(cfgs, u["x0"], u["y0"])

    sources, overrides = cell_sources(u, names, args.prompt, args.stage, REPO_ROOT)
    by_frame = {(a, f.name): sources[cell] for cell, (a, f) in u["cells"].items()}

    def illustration(area, f):
        return by_frame[(area, f.name)]

    def photo(area, f):
        return REPO_ROOT / "output" / area / "renders" / f"{f.name}.png"

    missing = {n: sum(not illustration(a, f).exists() for a, f in u["cells"].values() if a == n) for n in names}
    missing_photo = {n: sum(not photo(a, f).exists() for a, f in u["cells"].values() if a == n) for n in names}
    rail = [n for n in names if list((REPO_ROOT / "data" / "raw").glob(f"{n}_rail*.geojson"))]
    per_area = ", ".join(f"{n} {u['counts'][n]}" for n in names)
    print(f"union: {u['cols']} x {u['rows']} cells = {width:,} x {height:,} px; {len(u['cells'])} cells "
          f"({per_area}); "
          f"lattice corner ({u['x0']}, {u['y0']}) px; fit max error {fit['max_error_px']:.2e} px")
    print(f"illustration frames missing ({args.prompt}/{args.stage}): {missing}; photo frames missing: {missing_photo}"
          f"; rail credit from: {rail or 'none'}; band overrides (water_band/): {overrides or 'none'}")
    if args.dry_run:
        return
    if any(missing.values()) or (args.with_photo and any(missing_photo.values())):
        raise SystemExit("frames are missing; nothing written")

    out = REPO_ROOT / "output" / args.name / "tiles" / args.version
    if (out / "map.dzi").exists():
        raise SystemExit(f"{out} already exists; versions are immutable, pick a new --version")
    out.mkdir(parents=True, exist_ok=True)
    cells = union_mask(u, size)
    build_layer(union_layer(u, size, illustration), cells, out, "map", ".webp[lossless]")
    layers = {"illustration": "map.dzi"}
    if args.with_photo:
        # Each area's missing imagery, in union pixels, kept only on the cells it provides
        parts = []
        for cfg in cfgs:
            frame, cam, _ = setups[cfg["name"]]
            geom = nodata_geometry(cfg, frame, cam, u["x0"], u["y0"])
            own = unary_union([box(c * size, r * size, (c + 1) * size, (r + 1) * size)
                               for (c, r), (a, _) in u["cells"].items() if a == cfg["name"]])
            if not geom.is_empty:
                parts.append(geom.intersection(own))
        nodata = unary_union(parts) if parts else None
        build_layer(union_layer(u, size, photo), union_mask(u, size, nodata), out, "photo", ".webp[Q=82]")
        layers["photo"] = "photo.dzi"
    meta = {
        "area": args.name,
        "label": args.label or " + ".join(c["label"] for c in cfgs),
        "areas": [{"area": c["name"], "label": c["label"], "cells": u["counts"][c["name"]]} for c in cfgs],
        "version": args.version,
        "dzi": "map.dzi",
        "layers": layers,
        "width": width,
        "height": height,
        "background": "#%02x%02x%02x" % BACKGROUND,
        "fit": fit,
        "lattice_origin_px": [u["x0"], u["y0"]],
        "source": f"{args.prompt}/{args.stage}",
        "band_overrides": overrides,
        "built": date.today().isoformat(),
        "credits": CREDITS + (" " + RAIL_CREDIT if rail else "")
        + (" " + OSM_CREDIT if any((REPO_ROOT / "data" / "raw" / f"{n}_osm.json").exists() for n in names) else ""),
        "photo_credits": PHOTO_CREDITS,
    }
    (out / "map.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"-> {out}")

if __name__ == "__main__":
    main()
