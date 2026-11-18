"""Build the tree-canopy depth mask the live transit layer uses to hide
vehicles behind trees.

The trees on the map were drawn by the AI model, not taken from a city
dataset, so the only reliable record of where canopy appears is the v18
illustration itself. This script finds canopy by color in the full-resolution
v18 tiles and writes one 8-bit mask tile per map tile that has any.

Method, per 512 px tile at level 17:
  1. Strict color seeds. Lit canopy is a saturated, cool green: green within
     1 of the brightest channel, saturation (max - min) / max above SAT_MIN,
     red below RG_MAX x green and green below G_MAX. Lawns, meadows and
     ballfield grass are yellower (red / green 0.7-0.8), which is what the
     red / green cut is for; saturation alone let whole lawns through.
  2. A 3 x 3 opening drops seed speckle, then the seeds grow up to GROW_PX
     steps (4-connected) into a looser crown color, to take in shaded and
     yellower parts of a crown. The near-black outline stops the growth; the
     step limit bounds the leak where an outline is broken.
  3. Outlined crowns. Some crowns (much of Fairmount Park) are drawn in a
     lawn-like yellow green no color cut can separate. They are found by
     their outline instead: regions walled in by near-black pixels
     (thickened 1 px to close breaks), crown-sized and mostly green.
  4. A 3 x 3 closing fills small holes. Then every shape must show outline
     evidence: near-black pixels within OUTLINE_REACH px, enough in total
     and per pixel of area. Every crown the model draws has a dark outline
     along at least its lower edge; lawn and meadow patches, turf fields and
     painted courts that pass the color test have none, and this is the step
     that removes them.
  5. A 1 px dilation takes in the outline itself, and components under
     MIN_PIXELS are dropped.
  The tile is processed inside a window that reaches PAD px into its left,
  right and upper neighbors and BELOW px into the tile below, so canopies
  crossing a tile edge are treated as one shape.

Depth encoding. The map is drawn from a camera tilted 45 degrees, so a
tree's crown sits above (smaller screen y than) its trunk. A vehicle should
disappear behind a crown pixel only when the tree stands at or in front of
the vehicle, that is, when the trunk's screen y is at or below the vehicle's
ground point. For every canopy pixel the mask stores

    d = (y of the bottom of the vertical run of canopy pixels containing it,
         in the same column) - (pixel y) + TRUNK_PX

clamped to 1..255; 0 means no tree. TRUNK_PX = 4 is about 1.5 m of trunk at
45 degrees and 0.293 m per px. Runs continue across the bottom tile edge.
The viewer computes trunk y = pixel y + d and hides a vehicle pixel under
canopy when trunk y >= the vehicle's ground y.

Output: output/philly/overlays/v18/trees/
  trees_files/17/<x>_<y>.png  8-bit grayscale, only for tiles with canopy
  trees.json                  manifest: size, thresholds and the tile list

Limits. This is an estimate from color and outlines, not a tree inventory.
Tuned by eye on Rittenhouse Square, Germantown Ave, Belmont Plateau, the
Wissahickon, Kelly Drive, Franklin Field, Lincoln Financial Field, row-house
blocks and residential medians. Known misses: dark, desaturated crowns with
a broken outline (some along Kelly Drive) and the smallest 4-6 px street
trees. Known false hits: lawn a few px around a crown where its outline is
broken, and a few strips of cool-green grass next to outlined objects. The
depth assumes each column of a crown belongs to one tree, so stacked crowns
read as one taller tree. Only level 17 is built:
at lower zooms vehicles are too small for the difference to show.

Usage: .venv/bin/python scripts/40_build_tree_mask.py [--dry-run] [--force] [--only x0,y0,x1,y1] [--workers N]
"""

import argparse
import json
import multiprocessing as mp
import shutil
import time
from pathlib import Path

import numpy as np
import pyvips
from PIL import Image

from pixelphilly.projection import REPO_ROOT

TILES = REPO_ROOT / "output" / "philly" / "tiles" / "v18"
OUT = REPO_ROOT / "output" / "philly" / "overlays" / "v18" / "trees"
LEVEL = 17
TILE = 512

# Thresholds, tuned by eye on the check spots named in the docstring
SAT_MIN = 0.42      # lawns sit around 0.3-0.45, lit canopy 0.5-0.75
G_MAX = 190         # brighter greens are lime highlights, courts and turf lines
RG_MAX = 0.68       # red / green: canopy is a cool green, lawns, meadows and turf are yellower
GROW_SAT_MIN = 0.25  # looser test a crown is grown into from the strict seeds
GROW_RG_MAX = 0.80
GROW_G = (24, 140)  # the near-black outline stops growth; lit lawns are brighter than crowns
GROW_PX = 3         # growth steps; bounds any leak where a crown outline is broken
DARK_MAX = 50       # brightest channel of the near-black crown outline
CROWN_PX = (8, 6000)  # area of a region enclosed by outline that can be one crown
CROWN_SHARE = 0.85  # share of its pixels that must pass the crown color test
CROWN_RG_MAX = 0.85
CROWN_G_MAX = 170
OUTLINE_REACH = 2   # how far from a shape its outline evidence is counted
OUTLINE_HITS = 15   # evidence needed to keep a shape; see outline_hits
OUTLINE_DENSITY = 0.6  # and evidence per pixel of the shape
OPEN_SIZE = 3       # square opening: drops speckle narrower than 3 px
CLOSE_SIZE = 3      # square closing: fills 1-2 px holes inside a crown
OUTLINE_PX = 1      # dilation to take in the dark canopy outline
MIN_PIXELS = 12     # smallest component kept, after the steps above
TRUNK_PX = 4

PAD = 64            # context read from the left, right and upper neighbors; wider than a crown
BELOW = 256         # rows read from the tile below; d clamps at 255 anyway


def canopy_threshold(rgb):
    """True where a pixel's color is lit-canopy green (step 1 only)."""
    a = rgb[..., :3].astype(np.float32)
    mx = a.max(2)
    mn = a.min(2)
    sat = (mx - mn) / (mx + 1e-6)
    g = a[..., 1]
    return (g >= mx - 1) & (sat > SAT_MIN) & (g < G_MAX) & (a[..., 0] < RG_MAX * g)


def grow_candidates(rgb):
    """Looser color test: shaded and yellower parts of a crown, but also lawn.
    Only pixels connected to a strict seed through these are kept."""
    a = rgb[..., :3].astype(np.float32)
    mx = a.max(2)
    mn = a.min(2)
    sat = (mx - mn) / (mx + 1e-6)
    g = a[..., 1]
    return ((g >= mx - 1) & (sat > GROW_SAT_MIN) & (g > GROW_G[0]) & (g < GROW_G[1])
            & (a[..., 0] < GROW_RG_MAX * g))


def dilate_cross(m):
    """One step of 4-connected dilation. A 1 px diagonal outline still blocks
    it, which a square step would slip through."""
    out = m.copy()
    out[1:] |= m[:-1]
    out[:-1] |= m[1:]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _square(m, size, op):
    """Binary erosion (op=np.logical_and) or dilation (np.logical_or) with a
    size x size square. Outside the array counts as background for dilation
    and as foreground for erosion, so shapes touching the window edge are not
    eaten from the edge; the window is padded well past the tile anyway."""
    r = size // 2
    fill = op is np.logical_and
    p = np.pad(m, r, constant_values=fill)
    h, w = m.shape
    # Separable: a square is a row pass then a column pass
    out = p[:, 0:w].copy()
    for dx in range(1, size):
        op(out, p[:, dx:dx + w], out=out)
    res = out[0:h].copy()
    for dy in range(1, size):
        op(res, out[dy:dy + h], out=res)
    return res


def dilate(m, size):
    return _square(m, size, np.logical_or) if size > 1 else m


def erode(m, size):
    return _square(m, size, np.logical_and) if size > 1 else m


def _labels(m):
    """4-connected labels of a boolean array. libvips labels every region of
    equal value, so the background regions get labels too."""
    labels = np.asarray(pyvips.Image.new_from_array(m.astype(np.uint8)).labelregions())
    return (labels[..., 0] if labels.ndim == 3 else labels).astype(np.int64)


def outlined_crowns(rgb):
    """Crowns found by their outline rather than their color alone: regions
    fully enclosed by near-black pixels, crown-sized and mostly crown green.
    This catches yellower crowns, such as the Fairmount Park ones, whose
    color overlaps lawn: a lawn is never a small region walled in by black,
    and a turf field is not outlined at all."""
    a = rgb[..., :3].astype(np.float32)
    mx = a.max(2)
    mn = a.min(2)
    sat = (mx - mn) / (mx + 1e-6)
    g = a[..., 1]
    dark = mx < DARK_MAX
    if not dark.any():
        return np.zeros(dark.shape, bool)
    # Shaded crown sides go teal (blue a little above green), so the color
    # test here only asks for green clearly above red, which roads, roofs
    # and dirt fail
    green = (g > DARK_MAX) & (g < CROWN_G_MAX) & (a[..., 0] < CROWN_RG_MAX * g) & (sat > GROW_SAT_MIN)
    # The model's outlines have 1 px breaks and diagonal steps; thickening
    # them by 1 px closes those so the inside of a crown is its own region
    wall = dilate(dark, 3)
    labels = _labels(wall)
    n = labels.max() + 1
    size = np.bincount(labels.ravel(), minlength=n)
    n_wall = np.bincount(labels.ravel(), weights=wall.ravel(), minlength=n)
    n_green = np.bincount(labels.ravel(), weights=green.ravel(), minlength=n)
    # A region cut by the window edge may only look small, so it can't count
    edge = np.zeros(n, bool)
    edge[np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))] = True
    ok = ((n_wall == 0) & ~edge & (size >= CROWN_PX[0]) & (size <= CROWN_PX[1])
          & (n_green >= CROWN_SHARE * size))
    # Give back the pixel the thickening took from each side
    return dilate(ok[labels], 3)


def outline_hits(m, dark, r=OUTLINE_REACH):
    """Per pixel of m, the outline evidence of its 4-connected component: the
    number of (dark pixel, offset) pairs within r px that land on it, and the
    component's size. Lawn, meadow and turf patches that pass the color test
    have no outline near them; even a small street tree has one along its
    lower side. A lawn patch touching one crown borrows a little evidence, so
    the evidence is also judged per pixel of area: crowns and woods score
    1-3, lawn patches joined to a crown 0.4 or less."""
    labels = _labels(m)
    n = labels.max() + 1
    lab = np.where(m, labels, n)  # n = "not canopy", dropped below
    h, w = m.shape
    p = np.pad(lab, r, constant_values=n)
    hits = np.zeros(n + 1, np.int64)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            near = p[r + dy:r + dy + h, r + dx:r + dx + w][dark]
            hits += np.bincount(near, minlength=n + 1)
    hits[n] = 0
    size = np.bincount(lab.ravel(), minlength=n + 1)
    return hits[lab], size[lab]


def drop_small(m, min_pixels):
    """Remove 4-connected components smaller than min_pixels. libvips labels
    every region of equal value, so background regions get labels too; only
    the sizes of foreground labels matter."""
    if not m.any():
        return m
    labels = _labels(m)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_pixels
    return m & keep[labels]


def canopy_mask(rgb):
    """Canopy boolean for an RGB array (steps 1-5 of the module docstring)."""
    m = canopy_threshold(rgb)
    m = dilate(erode(m, OPEN_SIZE), OPEN_SIZE)
    if GROW_PX:
        cand = grow_candidates(rgb)
        for _ in range(GROW_PX):
            m = dilate_cross(m) & (cand | m)
    m |= outlined_crowns(rgb)
    m = erode(dilate(m, CLOSE_SIZE), CLOSE_SIZE)
    dark = rgb[..., :3].max(2) < DARK_MAX
    hits, size = outline_hits(m, dark)
    m &= (hits >= OUTLINE_HITS) & (hits >= OUTLINE_DENSITY * size)
    m = dilate(m, 2 * OUTLINE_PX + 1)
    return drop_small(m, MIN_PIXELS)


def depth_from_mask(m):
    """uint8 depth per pixel: distance to the bottom of the pixel's vertical
    canopy run in its column, plus TRUNK_PX, clamped to 1..255; 0 off canopy.
    A run reaching the last row is taken to end there."""
    h, w = m.shape
    bottom = np.zeros((h, w), np.int32)
    # Walk upward: a canopy pixel inherits the run bottom of the pixel below
    # it, or is the bottom itself when the pixel below is not canopy
    bottom[h - 1] = h - 1
    for y in range(h - 2, -1, -1):
        bottom[y] = np.where(m[y + 1], bottom[y + 1], y)
    d = bottom - np.arange(h, dtype=np.int32)[:, None] + TRUNK_PX
    return np.where(m, np.clip(d, 1, 255), 0).astype(np.uint8)


def load_tile(x, y):
    """RGB array of a v18 level-17 tile, or None outside the map."""
    p = TILES / "map_files" / str(LEVEL) / f"{x}_{y}.webp"
    if not p.exists():
        return None
    return np.asarray(Image.open(p).convert("RGB"))


def window(get_tile, x, y):
    """RGB window around tile (x, y): PAD px left, right and above, BELOW px
    below. Missing neighbors are black: never canopy, though at the map edge
    they count as outline evidence for a shape touching them."""
    h, w = PAD + TILE + BELOW, PAD + TILE + PAD
    win = np.zeros((h, w, 3), np.uint8)
    y0, x0 = y * TILE - PAD, x * TILE - PAD  # window origin in map px
    for ty in (y - 1, y, y + 1):
        for tx in (x - 1, x, x + 1):
            # Overlap of this tile with the window, in map px
            ax0, ax1 = max(tx * TILE, x0), min((tx + 1) * TILE, x0 + w)
            ay0, ay1 = max(ty * TILE, y0), min((ty + 1) * TILE, y0 + h)
            if ax0 >= ax1 or ay0 >= ay1:
                continue
            t = get_tile(tx, ty)
            if t is None:
                continue
            win[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = \
                t[ay0 - ty * TILE:ay1 - ty * TILE, ax0 - tx * TILE:ax1 - tx * TILE, :3]
    return win


def tile_depth(get_tile, x, y):
    """512 x 512 uint8 depth mask for tile (x, y)."""
    m = canopy_mask(window(get_tile, x, y))
    return depth_from_mask(m)[PAD:PAD + TILE, PAD:PAD + TILE]


def write_tile(folder, x, y, d):
    """Write a tile's mask as an 8-bit PNG if it has any canopy."""
    if not d.any():
        return False
    Image.fromarray(d, "L").save(Path(folder) / f"{x}_{y}.png", optimize=True)
    return True


def run_column_block(job):
    """Process tiles xs x ys top to bottom, keeping decoded tiles for the
    rows still needed so each source tile is decoded about once."""
    xs, ys, folder = job
    cache = {}

    def get(tx, ty):
        if (tx, ty) not in cache:
            cache[(tx, ty)] = load_tile(tx, ty)
        return cache[(tx, ty)]

    written = []
    for y in ys:
        for k in [k for k in cache if k[1] < y - 1]:
            del cache[k]
        for x in xs:
            if load_tile_exists(x, y) and write_tile(folder, x, y, tile_depth(get, x, y)):
                written.append(f"{x}_{y}")
    return written


def load_tile_exists(x, y):
    return (TILES / "map_files" / str(LEVEL) / f"{x}_{y}.webp").exists()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="check inputs and print the plan")
    ap.add_argument("--force", action="store_true", help="replace an existing build")
    ap.add_argument("--only", help="tile range x0,y0,x1,y1 (inclusive), for testing")
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument("--block", type=int, default=4, help="tile columns per job")
    args = ap.parse_args()

    meta = json.loads((TILES / "map.json").read_text())
    width, height = meta["width"], meta["height"]
    ncols, nrows = -(-width // TILE), -(-height // TILE)
    x0, y0, x1, y1 = 0, 0, ncols - 1, nrows - 1
    if args.only:
        x0, y0, x1, y1 = (int(v) for v in args.only.split(","))
    n = (x1 - x0 + 1) * (y1 - y0 + 1)
    print(f"v18 {width:,} x {height:,} px, {ncols} x {nrows} tiles; processing x {x0}-{x1}, y {y0}-{y1} "
          f"({n:,} tiles), {args.workers} workers")
    if not (TILES / "map_files" / str(LEVEL)).is_dir():
        raise SystemExit(f"no level-{LEVEL} tiles in {TILES}")
    if args.dry_run:
        return
    if (OUT / "trees.json").exists() and not args.force:
        raise SystemExit(f"{OUT} already built; pass --force to replace it")
    folder = OUT / "trees_files" / str(LEVEL)
    if folder.exists():
        shutil.rmtree(OUT / "trees_files")
    folder.mkdir(parents=True)

    t0 = time.time()
    ys = list(range(y0, y1 + 1))
    jobs = [(list(range(bx, min(bx + args.block, x1 + 1))), ys, folder) for bx in range(x0, x1 + 1, args.block)]
    tiles = []
    with mp.get_context("spawn").Pool(args.workers) as pool:
        for i, written in enumerate(pool.imap_unordered(run_column_block, jobs), 1):
            tiles += written
            print(f"  {i}/{len(jobs)} column blocks, {len(tiles):,} tiles with canopy", flush=True)

    tiles.sort(key=lambda s: tuple(int(v) for v in s.split("_")))
    info = {"map_version": "v18", "level": LEVEL, "tile_size": TILE, "width": width, "height": height,
            "trunk_px": TRUNK_PX, "tiles": tiles,
            "meaning": "0 = no tree; d > 0 = canopy whose trunk is at screen y = pixel y + d. Hide a vehicle "
                       "pixel under canopy when pixel y + d >= the vehicle's ground y.",
            "source": "canopy detected by color and outline in output/philly/tiles/v18/map_files/17 "
                      "(scripts/40_build_tree_mask.py); an estimate, not a tree inventory",
            "thresholds": {
                "seed": {"green_is_max_within": 1, "saturation_min": SAT_MIN, "green_max": G_MAX,
                         "red_over_green_max": RG_MAX, "open_square_px": OPEN_SIZE},
                "grow": {"steps_px": GROW_PX, "saturation_min": GROW_SAT_MIN,
                         "red_over_green_max": GROW_RG_MAX, "green_range": list(GROW_G)},
                "outlined_crown": {"outline_max_channel": DARK_MAX, "area_px": list(CROWN_PX),
                                   "green_share_min": CROWN_SHARE, "red_over_green_max": CROWN_RG_MAX,
                                   "green_max": CROWN_G_MAX},
                "outline_evidence": {"reach_px": OUTLINE_REACH, "hits_min": OUTLINE_HITS,
                                     "hits_per_px_min": OUTLINE_DENSITY},
                "close_square_px": CLOSE_SIZE, "outline_dilation_px": OUTLINE_PX,
                "min_component_px": MIN_PIXELS, "connectivity": 4}}
    if args.only:
        info["only"] = [x0, y0, x1, y1]
    (OUT / "trees.json").write_text(json.dumps(info, indent=1) + "\n")
    mb = sum(p.stat().st_size for p in folder.glob("*.png")) / 1e6
    print(f"trees: {len(tiles):,} tiles with canopy of {n:,}, {mb:.1f} MB, {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
