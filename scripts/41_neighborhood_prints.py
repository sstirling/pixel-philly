"""Cut one Philadelphia neighborhood out of the v18 map, as print and wallpaper
images.

Method: src/pixelphilly/neighborhoods.py builds the neighborhood's mask in map
px (ground inside the boundary, buildings by where they stand, using the
footprints and heights of the map's render scenes in data/processed, trees
by their trunk; see that module for the rule and its limits). This script crops the
full-resolution v18 tiles (level 17) to the mask's bounding box, shows the
map where the mask is set with a 1 px soft (antialiased) edge, and puts it
on the map's backdrop color (#ccd6e3) with a margin of 6% of the long side.
The neighborhood's name and the site address go small in the lower-left
corner, in the bottom margin, with flyover's text boxes
(scripts/29_flyover.py _text_box and _measure). Assembly is pyvips, so the
full-resolution image is streamed rather than held in memory.

Outputs: output/philly/prints/v18/<slug>/
  print.jpg    map px 1:1, the mask's bounding box plus the margin, with text
  desktop.jpg  5,120 x 2,880, the same composition fitted inside a 6% margin
  phone.jpg    1,290 x 2,796, a crop of the map that fills the screen (phone_rect)
  thumb.webp   600 px on the long side, no text
  preview.webp 1,920 x 1,080, the desktop image downscaled, for the page's
               click-to-enlarge view (a few hundred KB instead of a few MB)
and output/philly/prints/v18/index.json: per neighborhood built so far, the
name, slug, area (sq mi, from the boundary), each file's pixel size and
bytes, cut_by_map_edge (the boundary reaches past the map canvas) and
touches_top (something kept reaches the top of the work window, so a very
tall building could be cut off; expected false) and scene_buildings (how
many scene buildings were read; 0 means the column-run fallback was used). JPEGs are quality 92 with
no chroma subsampling; downscales are Lanczos.

Limits: the boundaries are informal neighborhoods, and the cut follows the
map's building and tree masks, which match the AI drawing closely but not
pixel for pixel (see neighborhoods.py). The phone image is a crop, not the
cut-out: a whole wide neighborhood came out small on a tall screen, so
Stephen chose a crop that fills it (Nov. 19). It's the full map (no
backdrop), so its edges can show bits of neighboring areas.

Boundaries: OpenDataPhilly, Philadelphia neighborhoods by Robert Cheetham,
CC BY 4.0 (data/raw/philadelphia-neighborhoods.geojson).

Usage:
  uv run python scripts/41_neighborhood_prints.py --only "Rittenhouse,Fishtown - Lower Kensington,Chestnut Hill"
  uv run python scripts/41_neighborhood_prints.py --all [--force]
  uv run python scripts/41_neighborhood_prints.py --previews   # preview.webp only, from desktop.jpg
--only takes exact LISTNAMEs separated by commas; names that contain a comma
("Mount Airy, East") are matched whole. A neighborhood whose folder exists
is skipped unless --force.
"""

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import numpy as np
import pyvips
from PIL import Image

from pixelphilly import neighborhoods as nb
from pixelphilly.projection import REPO_ROOT

_spec = importlib.util.spec_from_file_location("flyover", REPO_ROOT / "scripts" / "29_flyover.py")
fly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fly)

VERSION = "v18"
TILES = REPO_ROOT / "output" / "philly" / "tiles" / VERSION / "map_files" / "17"
MAP_JSON = REPO_ROOT / "output" / "philly" / "tiles" / VERSION / "map.json"
OCCLUSION = REPO_ROOT / "output" / "philly" / "overlays" / VERSION / "occlusion_files" / "17"
TREES_DIR = REPO_ROOT / "output" / "philly" / "overlays" / VERSION / "trees"
FROZEN = REPO_ROOT / "output" / "philly" / "FROZEN_v18.json"
BOUNDARIES = REPO_ROOT / "data" / "raw" / "philadelphia-neighborhoods.geojson"
OUT = REPO_ROOT / "output" / "philly" / "prints" / VERSION
TILE = 512

URL = "pixelphilly.sstirling.com"
BACKDROP_RGB = (0xCC, 0xD6, 0xE3)  # the map's own background (map.json "background")
MARGIN = 0.06  # of the long side
NAME_SIZE = 0.018  # of the short side
URL_SIZE = 0.62  # of the name size
DESKTOP = (5120, 2880)
PHONE = (1290, 2796)
THUMB_LONG = 600
PREVIEW = (1920, 1080)
FILES = ("print.jpg", "desktop.jpg", "phone.jpg", "thumb.webp", "preview.webp")
JPEG = {"Q": 92, "subsample_mode": "off", "optimize_coding": True, "strip": True}
CREDIT = ("Neighborhood boundaries: OpenDataPhilly, by Robert Cheetham, CC BY 4.0. "
          "Map: Pixel Philly v18, pixelphilly.sstirling.com.")


# ---- layout (pure, tested) ---------------------------------------------------

def margin_px(w: int, h: int) -> int:
    """The margin of a finished canvas of w x h: 6% of its long side."""
    return round(MARGIN * max(w, h))


def _label_parts(size, name, url):
    short = min(size)
    ns = max(10, round(NAME_SIZE * short))
    us = max(8, round(URL_SIZE * ns))
    return [(name, ns, max(2, ns // 3)), (url, us, max(2, us // 3))]


def label_boxes(size, name, url, margin=None):
    """[(x0, y0, x1, y1)] of the name box and the URL box under it, lower left.

    The block sits at the margin's left edge, centered in the bottom margin
    when it fits there, and is otherwise held a few px off the bottom edge.
    Boxes are clamped to the frame."""
    w, h = size
    m = margin_px(w, h) if margin is None else margin
    parts = _label_parts(size, name, url)
    dims = [fly._measure(t, s, p) for t, s, p in parts]
    block_h = sum(d[1] for d in dims)
    top = h - m + (m - block_h) // 2 if block_h <= m else h - block_h - max(2, h // 200)
    x = min(m, max(0, w - max(d[0] for d in dims)))
    boxes = []
    for bw, bh in dims:
        boxes.append((x, max(0, top), min(w, x + bw), min(h, top + bh)))
        top += bh
    return boxes


def draw_label(img: pyvips.Image, name: str, url: str, margin=None) -> pyvips.Image:
    """The name and URL boxes drawn on a pyvips RGB image. Only the corner the
    text covers is pulled into PIL, so this is cheap on a full-size print."""
    boxes = label_boxes((img.width, img.height), name, url, margin)
    px0, py0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    px1, py1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    patch = Image.fromarray(img.crop(px0, py0, px1 - px0, py1 - py0).numpy())
    for (text, s, p), (x0, y0, _, _) in zip(_label_parts((img.width, img.height), name, url), boxes):
        fly._text_box(patch, text, s, p, x0 - px0, y0 - py0, "left")
    return img.insert(pyvips.Image.new_from_array(np.asarray(patch)), px0, py0)


def phone_rect(bbox, center, canvas, size=PHONE):
    """The phone wallpaper's crop in map px, (x0, y0, x1, y1): the largest
    rectangle of the phone's shape that fits in the neighborhood's bounding
    box, centered on its center of mass and slid back inside the box. Never
    smaller than the screen itself (a small neighborhood is shown 1:1 with
    some of its surroundings rather than upscaled), and always inside the map."""
    bx0, by0, bx1, by1 = bbox
    aspect = size[0] / size[1]
    h = min(by1 - by0, (bx1 - bx0) / aspect)
    w = h * aspect
    if w < size[0]:
        w, h = size
    w, h = round(w), round(h)

    def place(c, lo, hi, n, limit):
        # Centered on c, then inside [lo, hi] if it fits there, then inside the map
        a = round(c - n / 2)
        if hi - lo >= n:
            a = min(max(a, lo), hi - n)
        return min(max(a, 0), limit - n)

    x0 = place(center[0], bx0, bx1, w, canvas[0])
    y0 = place(center[1], by0, by1, h, canvas[1])
    return x0, y0, x0 + w, y0 + h


def with_margin(art: pyvips.Image):
    """The print composition: art plus 6% of its long side on every side."""
    m = round(MARGIN * max(art.width, art.height))
    out = art.embed(m, m, art.width + 2 * m, art.height + 2 * m, extend="background", background=list(BACKDROP_RGB))
    return out, m


def fit_canvas(art: pyvips.Image, w: int, h: int) -> pyvips.Image:
    """art scaled (Lanczos) to fit inside w x h less the margin, centered on
    the backdrop; exactly w x h."""
    m = margin_px(w, h)
    scale = min((w - 2 * m) / art.width, (h - 2 * m) / art.height)
    r = art.resize(scale, kernel="lanczos3")
    # resize can round a px over; never let the art spill into the margin
    r = r.crop(0, 0, min(r.width, w - 2 * m), min(r.height, h - 2 * m))
    return r.embed((w - r.width) // 2, (h - r.height) // 2, w, h, extend="background", background=list(BACKDROP_RGB))


# ---- map reading -------------------------------------------------------------

def _tree_tiles():
    return set(json.loads((TREES_DIR / "trees.json").read_text())["tiles"])


def make_readers():
    trees = _tree_tiles()

    def building(tx, ty):
        p = OCCLUSION / f"{tx}_{ty}.png"
        if not p.exists():  # occlusion.json: a missing tile has no building
            return None
        return np.array(Image.open(p).convert("1"), bool)

    def tree(tx, ty):
        if f"{tx}_{ty}" not in trees:
            return None
        return np.array(Image.open(TREES_DIR / "trees_files" / "17" / f"{tx}_{ty}.png").convert("L"), np.uint8)

    return building, tree


def map_crop(x0, y0, x1, y1) -> pyvips.Image:
    """The full-resolution map for [x0, x1) x [y0, y1) in map px, from tiles."""
    tx0, ty0, tx1, ty1 = x0 // TILE, y0 // TILE, (x1 - 1) // TILE + 1, (y1 - 1) // TILE + 1
    tiles = [pyvips.Image.new_from_file(str(TILES / f"{tx}_{ty}.webp"))
             for ty in range(ty0, ty1) for tx in range(tx0, tx1)]
    big = pyvips.Image.arrayjoin(tiles, across=tx1 - tx0)
    return big.crop(x0 - tx0 * TILE, y0 - ty0 * TILE, x1 - x0, y1 - y0)


def blend(rgb: pyvips.Image, mask_u8: np.ndarray) -> pyvips.Image:
    """The map where the mask is set, the backdrop elsewhere, with a 1 px soft
    edge: the 0/255 mask is smoothed by a 3 x 3 binomial kernel, so edge pixels
    take partial weights instead of a hard stair-step."""
    a = pyvips.Image.new_from_memory(mask_u8.data, mask_u8.shape[1], mask_u8.shape[0], 1, "uchar")
    k = pyvips.Image.new_from_array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], scale=16)
    a = a.conv(k, precision="integer")
    out = (rgb * a + (255 - a) * list(BACKDROP_RGB)) / 255
    return (out + 0.5).cast("uchar")


# ---- one neighborhood ----------------------------------------------------------

def make_preview(dest: Path) -> None:
    """preview.webp from the neighborhood's desktop.jpg (same 16:9 shape)."""
    d = pyvips.Image.new_from_file(str(dest / "desktop.jpg"))
    d.resize(PREVIEW[0] / d.width, kernel="lanczos3").webpsave(str(dest / "preview.webp"), Q=82, strip=True)


def _info(path: Path) -> dict:
    img = pyvips.Image.new_from_file(str(path))
    return {"width": img.width, "height": img.height, "bytes": path.stat().st_size}


def build(hood: dict, fit: dict, size, readers, scenes, dest: Path) -> dict:
    t0 = time.time()
    polys = nb.project_polygons(hood["polygons_lonlat"], fit)
    prisms = scenes.prisms(nb.neighborhood_window(polys, *size)) if scenes else None
    m = nb.neighborhood_mask(polys, *readers, *size, tile=TILE, prisms=prisms)
    t_mask = time.time() - t0
    if m["touches_top"]:
        print(f"  warning: something kept reaches the window's top; a tall building may be cut off")
    bbox = nb.mask_bbox(m["mask"])
    if bbox is None:
        raise RuntimeError(f"{hood['name']}: empty mask")
    ox, oy = m["origin"]
    bx0, by0, bx1, by1 = bbox
    sub = m["mask"][by0:by1, bx0:bx1]
    # Center of mass from row and column counts (no coordinate arrays: the
    # largest masks are hundreds of megapixels)
    rows, cols = sub.sum(axis=1, dtype=np.int64), sub.sum(axis=0, dtype=np.int64)
    total = max(int(rows.sum()), 1)
    center = (ox + bx0 + float((cols * np.arange(len(cols))).sum()) / total,
              oy + by0 + float((rows * np.arange(len(rows))).sum()) / total)
    mask_u8 = np.ascontiguousarray(sub, dtype=np.uint8) * np.uint8(255)
    del m["mask"], sub
    x0, y0, x1, y1 = bx0 + ox, by0 + oy, bx1 + ox, by1 + oy

    dest.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=f".{dest.name}-") as tmp:
        # Write the blended art once, so the four outputs read a plain file
        # instead of re-running the tile join and blend four times
        art_path = Path(tmp) / "art.v"
        blend(map_crop(x0, y0, x1, y1), mask_u8).write_to_file(str(art_path))
        del mask_u8
        art = pyvips.Image.new_from_file(str(art_path))

        framed, margin = with_margin(art)
        draw_label(framed, hood["name"], URL, margin).jpegsave(str(dest / "print.jpg"), **JPEG)
        draw_label(fit_canvas(art, *DESKTOP), hood["name"], URL).jpegsave(str(dest / "desktop.jpg"), **JPEG)
        px0, py0, px1, py1 = phone_rect((x0, y0, x1, y1), center, size)
        phone = map_crop(px0, py0, px1, py1)
        if phone.width != PHONE[0]:
            phone = phone.resize(PHONE[0] / phone.width, kernel="lanczos3")
        phone = phone.crop(0, 0, min(phone.width, PHONE[0]), min(phone.height, PHONE[1]))
        phone = phone.embed(0, 0, *PHONE, extend="copy")  # a rounding px short, at most
        draw_label(phone, hood["name"], URL).jpegsave(str(dest / "phone.jpg"), **JPEG)
        thumb = framed.resize(THUMB_LONG / max(framed.width, framed.height), kernel="lanczos3")
        thumb.webpsave(str(dest / "thumb.webp"), Q=85, strip=True)
        del art, framed, thumb
    make_preview(dest)

    files = {f: _info(dest / f) for f in FILES}
    return {"name": hood["name"], "slug": hood["slug"], "sqmi": round(hood["sqmi"], 4),
            "map_bbox_px": [x0, y0, x1, y1], "phone_crop_px": [px0, py0, px1, py1], "cut_by_map_edge": m["cut_by_map_edge"],
            "touches_top": m["touches_top"], "scene_buildings": len(prisms) if prisms else 0, "files": files,
            "seconds": {"mask": round(t_mask, 1), "total": round(time.time() - t0, 1)}}


def parse_only(text: str, names) -> list[str]:
    """Split on commas, but match the longest run of pieces that is a real
    name first, since some LISTNAMEs contain a comma."""
    known = set(names)
    parts, out, i = text.split(","), [], 0
    while i < len(parts):
        for j in range(len(parts), i, -1):
            cand = ",".join(parts[i:j]).strip()
            if cand in known:
                out.append(cand)
                i = j
                break
        else:
            sys.exit(f"--only: no neighborhood named {parts[i].strip()!r} (use exact LISTNAMEs)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--only", help="exact LISTNAMEs, comma separated")
    g.add_argument("--all", action="store_true")
    g.add_argument("--previews", action="store_true", help="only (re)make preview.webp from existing desktop.jpg files")
    ap.add_argument("--force", action="store_true", help="replace existing neighborhood folders")
    args = ap.parse_args()

    if args.previews:
        index_path = OUT / "index.json"
        index = json.loads(index_path.read_text())
        t0 = time.time()
        for e in index["neighborhoods"]:
            make_preview(OUT / e["slug"])
            e["files"]["preview.webp"] = _info(OUT / e["slug"] / "preview.webp")
        index_path.write_text(json.dumps(index, indent=1) + "\n")
        mb = sum(e["files"]["preview.webp"]["bytes"] for e in index["neighborhoods"]) / 1e6
        print(f"{len(index['neighborhoods'])} previews, {mb:.1f} MB, {time.time() - t0:.1f} s")
        return

    meta = json.loads(MAP_JSON.read_text())
    size = (meta["width"], meta["height"])
    hoods = nb.load_neighborhoods(BOUNDARIES)
    if args.all:
        todo = hoods
    else:
        wanted = parse_only(args.only, [h["name"] for h in hoods])
        todo = [h for h in hoods if h["name"] in wanted]

    readers = make_readers()
    frozen = json.loads(FROZEN.read_text())
    scenes = nb.SceneBuildings(frozen["regions_in_precedence_order"], meta["lattice_origin_px"])
    if not scenes.available():
        print("warning: render scenes (data/processed) missing; buildings go by the column-run rule only")
        scenes = None
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    entries = {e["slug"]: e for e in index.get("neighborhoods", [])}

    t_all = time.time()
    built = []
    for hood in todo:
        dest = OUT / hood["slug"]
        if dest.exists():
            if not args.force:
                print(f"{hood['name']}: {dest.relative_to(REPO_ROOT)} exists, skipping (use --force)")
                continue
            shutil.rmtree(dest)
        print(f"{hood['name']} ({hood['sqmi']:.2f} sq mi) -> {dest.relative_to(REPO_ROOT)}", flush=True)
        e = build(hood, meta["fit"], size, readers, scenes, dest)
        entries[e["slug"]] = e
        built.append(e)
        for f, v in e["files"].items():
            print(f"  {f:12s} {v['width']:>6} x {v['height']:<6} {v['bytes'] / 1e6:7.2f} MB")
        print(f"  {e['seconds']['total']:.1f} s (mask {e['seconds']['mask']:.1f} s)", flush=True)

        # Rewrite the index after each one, so an interrupted --all keeps what it made
        OUT.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps({
            "map_version": VERSION, "updated": date.today().isoformat(), "credit": CREDIT,
            "backdrop": "#ccd6e3",
            "neighborhoods": sorted(entries.values(), key=lambda x: x["slug"])}, indent=1) + "\n")

    total = sum(v["bytes"] for e in built for v in e["files"].values())
    print(f"built {len(built)} in {time.time() - t_all:.1f} s, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
