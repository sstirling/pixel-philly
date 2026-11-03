"""Dormant lawns in the leaf-off aerial, shifted toward green.

The City's 2024 aerial was flown in March: lawns under bare trees are
brown-tan, and the drawing model draws them as dirt (Independence Square,
Washington Square). Inside park polygons only (City PPR_Properties; the
National Park Service's Independence NHP boundary, which the City layer
lacks), pixels classified as dormant grass get their hue moved toward lawn
green. Brightness is kept, so mowing stripes, shade and tree shadows stay.
Paint only, opt-in per config ("lawn_correct": true), applied to the ground
texture before rendering; roofs are excluded (building footprints).

Classification, from measured cluster colors in the 2024 aerial
(atlas_indhall_fac ground): dormant grass H 43-54, S 0.25-0.40, V 0.33-0.65
(Washington Square, Independence Square, the Mall); paths and paving S
0.06-0.20, V 0.65-0.93; shadow V < 0.25; ball-field clay is redder (H ~20-30).
DORMANT_BAND sits between them, with soft edges (EDGE) so lawn meets path
without a seam. Bare dirt in a park is the main risk: brown dirt with grass-
like hue and saturation would turn green too.
"""

from __future__ import annotations

import numpy as np

from .invented_water import _hsv

DORMANT_BAND = {"h": (35.0, 65.0), "s": (0.22, 0.60), "v": (0.30, 0.72)}
EDGE = {"h": 6.0, "s": 0.04, "v": 0.06}  # soft ramp width just inside each band edge
TARGET_HUE = 88.0  # lawn green
MIN_SAT = 0.30
STRENGTH = 0.9


def _ramp(x, lo, hi, w):
    """1 well inside [lo, hi], falling linearly to 0 over w at each edge."""
    return np.clip(np.minimum(x - lo, hi - x) / w, 0.0, 1.0)


def dormant_weight(rgb) -> np.ndarray:
    h, s, v = _hsv(rgb)
    b = DORMANT_BAND
    return (_ramp(h, *b["h"], EDGE["h"]) * _ramp(s, *b["s"], EDGE["s"]) * _ramp(v, *b["v"], EDGE["v"]))


def _hsv_to_rgb(h, s, v):
    h = (h % 360.0) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def correct(rgb: np.ndarray, region: np.ndarray) -> np.ndarray:
    """rgb (H, W, 3) uint8; region (H, W) bool (park polygons minus building
    footprints) or float 0-1 (the same, faded out in woods). Returns a
    corrected copy; pixels outside the region or not dormant grass are
    unchanged."""
    out = rgb.copy()
    w = dormant_weight(rgb) * region
    sel = w > 0
    if not sel.any():
        return out
    h, s, v = _hsv(rgb[sel])
    k = w[sel] * STRENGTH
    h2 = h + (TARGET_HUE - h) * k
    s2 = s + (np.maximum(s, MIN_SAT) - s) * k
    out[sel] = np.clip(np.round(_hsv_to_rgb(h2, s2, v) * 255), 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------- woods
# The forest floor in leaf-off woods (leaf litter) falls in DORMANT_BAND too:
# in atlas_wissahickon_fac the correction turned 42% of park pixels green
# (13.4 of 31.6 million). Woods are told apart from lawns under trees with
# the LiDAR grid (data/processed/<area>_lidar_grid.npz): even leaf-off,
# branches return points well above the ground, so woods are where nearly
# every cell around a point is canopy. Measured over whole park polygons
# (cells over CANOPY_H_M, buildings excluded, share within WOODS_RADIUS_M):
#   Wissahickon Valley Park: share > 0.7 for 80% of its cells
#   Washington Square 2.3%, Independence NHP 4.4%, Clark Park 11%,
#   Malcolm X Park 1.1%, West Fairmount Park lawns 0% (all lawns with big
#   trees); Cobbs Creek Park 36% (wooded creek valley plus lawns)
# Per cell alone, canopy doesn't separate them (Washington Square 59% of
# cells over 2.5 m, Wissahickon 78%): the 30 m neighborhood does. The ramp
# WOODS_COVER fades the correction out between 0.65 and 0.75 so there's no
# hard line where woods meet lawn.
CANOPY_H_M = 2.5  # above shrubs and parked cars; leaf-off branches clear it
WOODS_RADIUS_M = 30.0
WOODS_COVER = (0.65, 0.75)
WOODS_FEATHER_M = 8.0  # edge feather half-width (m): woods fade in over ~16 m
WOODS_BLOCK_M = 2.0  # computed on 2 m blocks: the South Philly grid is 14k x 21k cells


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 window (edges padded by repetition)."""
    k = 2 * r + 1
    p = np.pad(a.astype(np.float64), ((r + 1, r), (r + 1, r)), mode="edge")
    c = p.cumsum(0).cumsum(1)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def woods_grid(h: np.ndarray, res: float, feather_m: float = 0.0):
    """(weight, block_m): how much each WOODS_BLOCK_M block is woods, 0-1.
    h: height above ground per cell (dsm - ground, m), NaN where there is
    no ground return or a building; such cells count as neither canopy nor
    open ground. Block (0, 0) starts at the grid's north-west corner."""
    k = max(1, int(round(WOODS_BLOCK_M / res)))
    rows, cols = h.shape[0] // k * k, h.shape[1] // k * k
    if rows == 0 or cols == 0:
        return np.zeros((0, 0), np.float32), k * res
    hb = h[:rows, :cols].reshape(rows // k, k, cols // k, k)
    valid = np.isfinite(hb)
    with np.errstate(invalid="ignore"):
        canopy = (np.where(valid, hb, 0.0) > CANOPY_H_M).sum(axis=(1, 3)).astype(np.float64)
    n_valid = valid.sum(axis=(1, 3)).astype(np.float64)
    r = int(round(WOODS_RADIUS_M / (k * res)))
    num, den = _box_mean(canopy, r), _box_mean(n_valid, r)
    cover = np.where(den > 0, num / np.maximum(den, 1e-9), 0.0)
    lo, hi = WOODS_COVER
    w = np.clip((cover - lo) / (hi - lo), 0.0, 1.0)
    # Forest mode only (feather_m=WOODS_FEATHER_M): the ramp alone turns
    # woods on within ~6 m, which drew a hard forest-green edge with a brown
    # fringe (north|west_north, Nov. 3). Two box passes (a triangle filter)
    # spread it over ~feather_m * 2. Off by default, so lawn_skip_woods scenes
    # stay as drawn in v9
    rf = int(round(feather_m / 2 / (k * res)))
    for _ in range(2 if rf > 0 else 0):
        w = _box_mean(w, rf)
    return w.astype(np.float32), k * res


def sample_grid(grid: np.ndarray, origin, cell_m: float, e, n) -> np.ndarray:
    """Nearest-cell values of `grid` (row 0 at the north edge; origin = (west
    edge, north edge) in local m) at local points; 0 outside the grid."""
    e, n = np.asarray(e, float), np.asarray(n, float)
    c = np.floor((e - origin[0]) / cell_m).astype(np.int64)
    r = np.floor((origin[1] - n) / cell_m).astype(np.int64)
    inside = (r >= 0) & (r < grid.shape[0]) & (c >= 0) & (c < grid.shape[1])
    out = np.zeros(e.shape, np.float32)
    out[inside] = grid[r[inside], c[inside]]
    return out


# ---------------------------------------------------------------- forest
# "lawn_woods_mode": "forest" (with lawn_skip_woods): woods are shifted
# toward forest green instead of left as the leaf-off aerial, which the model
# drew dark brown to black (the north|west_north join, Nov. 2). The target
# is the renderer's own tree-canopy color (render/render.js tints canopies
# HSL h 0.27-0.33, s 0.35-0.50, l 0.30-0.38; the midpoint in HSV is about
# h 108, s 0.59, v 0.48), so woods read as trees, 20 degrees bluer and
# darker than mowed lawn (TARGET_HUE 88). Brightness is remapped linearly
# into FOREST["v"], keeping its order (texture) but with a floor, so tree
# shadows can't become black patches. Paving (paths, park roads) is left
# alone; mapped water is excluded by the caller (05_build_scene.py).
FOREST = {"h": 108.0, "s": 0.55, "v": (0.26, 0.56)}
FOREST_HUE_BAND = (95.0, 121.0)
FOREST_V_IN = 0.80  # aerial value mapped to the top of FOREST["v"]
PAVING = {"s_max": 0.12, "v_min": 0.22}  # neutral, not shadow-dark: paths and roads


def paving(rgb) -> np.ndarray:
    _, s, v = _hsv(rgb)
    return (s < PAVING["s_max"]) & (v >= PAVING["v_min"])


def forest(rgb: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """rgb (H, W, 3) uint8; weight (H, W) 0-1 (park x woods x not water).
    Returns a copy with woods pixels moved toward forest green by `weight`."""
    out = rgb.copy()
    w = weight * ~paving(rgb)
    sel = w > 0
    if not sel.any():
        return out
    h, s, v = _hsv(rgb[sel])
    k = w[sel]
    lo, hi = FOREST["v"]
    v_target = lo + (hi - lo) * np.clip(v / FOREST_V_IN, 0.0, 1.0)
    h2 = h + (FOREST["h"] - h) * k
    s2 = s + (FOREST["s"] - s) * k
    v2 = v + (v_target - v) * k
    out[sel] = np.clip(np.round(_hsv_to_rgb(h2, s2, v2) * 255), 0, 255).astype(np.uint8)
    return out


# ------------------------------------------------------------ woods trees
# Experiment (Nov. 3; "woods_trees": "lidar", opt-in): forest mode's smooth
# green ground was drawn as lakes. Instead, woods get the same stylized
# canopy balls the renderer draws for the street-tree inventory, one per
# TREE_SPACING_M block at the block's highest LiDAR cell, so the model sees
# trees and draws trees. Crowns are sized to close the canopy between them.
TREE_SPACING_M = 7.0
TREE_MIN_H_M = 5.0  # a treetop, not a shrub
TREE_RADIUS_M = (3.0, 5.0)  # render radius (05_build_scene.tree_radius_m clamps street trees to 1.5-7 m)


def canopy_trees(h: np.ndarray, res: float, origin, woods: np.ndarray, woods_block_m: float) -> list:
    """[(e, n, radius_m)] treetops in woods. h: height above ground (m, NaN
    = no data or building) on the grid at `origin` (west, north edge, local
    m) and `res`; woods: woods_grid weights on `woods_block_m` blocks over
    the same grid."""
    k = max(1, int(round(TREE_SPACING_M / res)))
    rows, cols = h.shape[0] // k, h.shape[1] // k
    out = []
    if rows == 0 or cols == 0:
        return out
    hb = np.where(np.isfinite(h[:rows * k, :cols * k]), h[:rows * k, :cols * k], -1.0)
    hb = hb.reshape(rows, k, cols, k).transpose(0, 2, 1, 3).reshape(rows, cols, k * k)
    arg = hb.argmax(axis=2)
    top = np.take_along_axis(hb, arg[..., None], axis=2)[..., 0]
    for br, bc in zip(*np.nonzero(top > TREE_MIN_H_M)):
        r = br * k + arg[br, bc] // k
        c = bc * k + arg[br, bc] % k
        e = origin[0] + (c + 0.5) * res
        n = origin[1] - (r + 0.5) * res
        wr, wc = int((r * res) / woods_block_m), int((c * res) / woods_block_m)
        if wr >= woods.shape[0] or wc >= woods.shape[1] or woods[wr, wc] <= 0.5:
            continue
        rad = float(np.clip(0.6 * TREE_SPACING_M * (0.8 + 0.2 * min(top[br, bc], 25.0) / 25.0),
                            *TREE_RADIUS_M))
        out.append((round(float(e), 2), round(float(n), 2), round(rad, 2)))
    return out
