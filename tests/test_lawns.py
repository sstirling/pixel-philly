"""Dormant lawns in the leaf-off aerial: shift brown grass toward green inside
park polygons, nothing else."""

import numpy as np
import pytest

from pixelphilly import lawns
from pixelphilly.invented_water import _hsv

# Measured cluster colors from the 2024 aerial (atlas_indhall_fac ground)
GRASS = (148, 137, 98)  # Washington Square lawn: H 46, S 0.34, V 0.58
GRASS_DARK = (126, 115, 80)  # the same lawn in part shade: V 0.49
PATH = (191, 184, 158)  # Mall paths: S 0.17, V 0.75
PALE = (236, 236, 222)  # paving: S 0.06, V 0.93
SHADOW = (42, 43, 44)
CLAY = (182, 112, 72)  # a ball-field infield: H 22
ROOF = (148, 137, 98)  # a roof the same color as the lawn (outside the region: excluded footprint)


def _tile(colors):
    return np.array([colors], np.uint8)


def test_dormant_grass_turns_green_and_keeps_its_texture():
    px = _tile([GRASS, GRASS_DARK])
    out = lawns.correct(px, np.ones(px.shape[:2], bool))
    h, s, v = _hsv(out[0])
    assert all(75 <= x <= 100 for x in h), h
    assert out[0, 0, 1] > out[0, 0, 0], "greener than red"
    v0 = _hsv(px[0])[2]
    assert np.allclose(v, v0, atol=0.01), "brightness (texture) kept"
    assert v[0] > v[1], "light and shaded grass stay distinct"


def test_paths_paving_shadows_and_clay_are_unchanged():
    px = _tile([PATH, PALE, SHADOW, CLAY])
    out = lawns.correct(px, np.ones(px.shape[:2], bool))
    assert np.array_equal(out, px)


def test_nothing_changes_outside_the_park_polygons():
    px = _tile([GRASS, ROOF])
    region = np.array([[True, False]])
    out = lawns.correct(px, region)
    assert not np.array_equal(out[0, 0], px[0, 0]) and np.array_equal(out[0, 1], px[0, 1])


def test_band_edges_are_soft():
    # A pixel just inside the band edge (S 0.224, between path and grass) moves
    # less than full grass, so there's no hard seam between lawn and path
    edge = _tile([(165, 155, 128), GRASS])
    out = lawns.correct(edge, np.ones(edge.shape[:2], bool))
    shift = np.abs(_hsv(out[0])[0] - _hsv(edge[0])[0])
    assert 0 < shift[0] < shift[1]


# ------------------------------------------------------------------ woods
# Leaf-off woods: the forest floor (leaf litter) reads as dormant grass in the
# March aerial, and the correction tinted 42% of atlas_wissahickon_fac's park
# pixels green. Woods are told apart from lawns under trees by LiDAR canopy
# cover around each point (cells > CANOPY_H_M above ground, within
# WOODS_RADIUS_M). Fixtures: 200 x 200 m patches of height above ground
# (0.5 m cells; NaN = no ground return or a building) from the area grids.

from pathlib import Path  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def _patch(name):
    return np.load(FIX / f"lawn_woods_{name}.npz")["h"].astype(np.float32)


def _center(weight):
    # The middle 100 m, where the 30 m window lies wholly inside the patch
    n = weight.shape[0]
    return weight[n // 4: 3 * n // 4, n // 4: 3 * n // 4]


def test_wissahickon_woods_are_woods():
    w, block = lawns.woods_grid(_patch("wissahickon"), 0.5)
    assert block == lawns.WOODS_BLOCK_M
    assert _center(w).mean() > 0.6


def test_lawns_under_city_trees_are_not_woods():
    # Washington Square and Clark Park: big trees over dormant lawns, which
    # the correction is meant to green
    for name in ("washington_sq", "clark_park"):
        assert _center(lawns.woods_grid(_patch(name), 0.5)[0]).mean() < 0.1, name


def test_woods_grid_on_synthetic_heights():
    rng = np.random.default_rng(0)
    h = np.zeros((400, 400), np.float32)
    h[:, :200] = np.where(rng.random((400, 200)) < 0.85, 18.0, 0.2)  # forest, west half
    yy, xx = np.mgrid[:400, :400]
    for cy, cx in ((100, 300), (300, 260), (200, 360)):  # three 12 m trees on the east lawn
        h[(yy - cy) ** 2 + (xx - cx) ** 2 < 12**2] = 15.0
    w, block = lawns.woods_grid(h, 0.5)
    k = int(block / 0.5)
    assert w[:, : 120 // k].mean() > 0.95  # deep in the forest
    assert w[:, 300 // k:].max() == 0.0  # lawn with scattered trees
    # No data counts as neither canopy nor ground
    h2 = h.copy()
    h2[:, 200:] = np.nan
    assert np.isfinite(lawns.woods_grid(h2, 0.5)[0]).all()


def test_sample_grid_nearest_and_outside():
    w = np.array([[0.0, 1.0], [0.5, 0.25]], np.float32)
    origin = (100.0, 50.0)  # west edge, north edge, local m
    e = np.array([100.5, 103.9, 101.0, 103.0, 99.0, 106.0])
    n = np.array([49.0, 49.0, 46.5, 46.5, 49.0, 49.0])
    got = lawns.sample_grid(w, origin, 2.0, e, n)
    assert np.allclose(got, [0.0, 1.0, 0.5, 0.25, 0.0, 0.0])


def test_float_region_scales_the_correction():
    px = _tile([GRASS, GRASS, GRASS])
    full = lawns.correct(px, np.ones(px.shape[:2], bool))
    out = lawns.correct(px, np.array([[1.0, 0.0, 0.5]]))
    assert np.array_equal(out[0, 0], full[0, 0])
    assert np.array_equal(out[0, 1], px[0, 1])
    h = _hsv(out[0])[0]
    assert _hsv(px[0])[0][2] < h[2] < h[0]


# ------------------------------------------------------------------ forest
# "lawn_woods_mode": "forest": leaf-off woods drawn as woods (forest green),
# not left as the brown aerial (the model drew those dark brown to black at
# the north|west_north join, seam median 3.44). Fixtures: 160 px crops of the
# 2024 aerial (5 px median, as on the ground texture) inside woods.

from PIL import Image  # noqa: E402


def _aerial(name):
    return np.asarray(Image.open(FIX / f"lawn_forest_{name}_aerial.png").convert("RGB"))


def test_forest_target_comes_from_the_rendered_tree_canopy():
    # render/render.js tints canopies HSL h 0.27-0.33, s 0.35-0.50, l 0.30-0.38
    h, s, v = lawns.FOREST["h"], lawns.FOREST["s"], np.mean(lawns.FOREST["v"])
    assert 0.27 * 360 <= h <= 0.33 * 360
    assert abs(h - lawns.TARGET_HUE) >= 15, "woods must read apart from mowed lawn"
    assert 0.3 <= v <= 0.6 and s >= 0.4


@pytest.mark.parametrize("name", ["wissahickon", "westfairmount"])
def test_woods_turn_forest_green_with_texture_and_no_dark_patches(name):
    rgb = _aerial(name)
    out = lawns.forest(rgb, np.ones(rgb.shape[:2], np.float32))
    h, s, v = _hsv(out)
    h0, s0, v0 = _hsv(rgb)
    paving = lawns.paving(rgb)
    assert paving.mean() < 0.05
    woods = ~paving
    lo, hi = lawns.FOREST_HUE_BAND
    assert ((h[woods] >= lo) & (h[woods] <= hi)).all()
    assert v[woods].min() >= lawns.FOREST["v"][0] - 0.01, "no black patches"
    assert v[woods].max() <= lawns.FOREST["v"][1] + 0.01
    # Texture kept: brightness keeps its order and some spread
    assert np.corrcoef(v0[woods], v[woods])[0, 1] > 0.95
    assert v[woods].std() > 0.03


def test_forest_leaves_lawns_alone_where_there_are_no_woods():
    rgb = _aerial("washington_sq")
    assert np.array_equal(lawns.forest(rgb, np.zeros(rgb.shape[:2], np.float32)), rgb)
    # Lawns under big city trees are almost never woods: the same 30 m share
    # and 0.65-0.75 fade as lawn_skip_woods, so a few blocks get a small
    # weight (Washington Square: 11% of blocks, mean 0.17) and almost none
    # are mostly woods
    for name, most in (("washington_sq", 0.01), ("clark_park", 0.03)):
        c = _center(lawns.woods_grid(_patch(name), 0.5)[0])
        assert (c > 0.5).mean() < most and c.mean() < 0.05, name


def test_forest_skips_paving_and_fades_with_weight():
    px = np.array([[(128, 128, 126), (120, 96, 70), (120, 96, 70)]], np.uint8)  # path, leaf litter x2
    out = lawns.forest(px, np.array([[1.0, 1.0, 0.5]], np.float32))
    assert np.array_equal(out[0, 0], px[0, 0])
    h = _hsv(out[0])[0]
    assert lawns.FOREST_HUE_BAND[0] <= h[1] <= lawns.FOREST_HUE_BAND[1]
    assert _hsv(px[0])[0][2] < h[2] < h[1]


def test_woods_edge_is_feathered_over_10_to_20_m():
    # A hard forest edge (the north|west_north crop, Nov. 3): the weight must
    # rise from 0.1 to 0.9 over 10-20 m, not within one 2 m block
    rng = np.random.default_rng(1)
    h = np.zeros((400, 400), np.float32)
    h[:, :200] = np.where(rng.random((400, 200)) < 0.9, 18.0, 0.2)
    w, block = lawns.woods_grid(h, 0.5, feather_m=lawns.WOODS_FEATHER_M)
    prof = w[40:60].mean(axis=0)
    i10 = int(np.argmax(prof < 0.9))
    i90 = int(np.argmax(prof < 0.1))
    assert 10.0 <= (i90 - i10) * block <= 20.0, (i10, i90, prof[i10 - 2:i90 + 2])


def test_feather_is_off_by_default_so_v9_scenes_reproduce():
    rng = np.random.default_rng(1)
    h = np.zeros((400, 400), np.float32)
    h[:, :200] = np.where(rng.random((400, 200)) < 0.9, 18.0, 0.2)
    w, block = lawns.woods_grid(h, 0.5)
    prof = w[40:60].mean(axis=0)
    i10, i90 = int(np.argmax(prof < 0.9)), int(np.argmax(prof < 0.1))
    assert (i90 - i10) * block <= 6.0


# ------------------------------------------------------------- woods trees
# Experiment (Nov. 3): woods drawn as rendered tree canopies at LiDAR
# treetops instead of a ground tint (forest mode invented lakes).


def test_canopy_trees_one_per_block_in_woods_only():
    rng = np.random.default_rng(2)
    h = np.zeros((400, 400), np.float32)
    h[:, :200] = np.where(rng.random((400, 200)) < 0.9, rng.uniform(8, 25, (400, 200)), 0.2)
    w, block = lawns.woods_grid(h, 0.5)
    origin = (0.0, 200.0)  # west, north edge (local m)
    trees = lawns.canopy_trees(h, 0.5, origin, w, block)
    assert trees, "woods get trees"
    xs = np.array([t[0] for t in trees]); ys = np.array([t[1] for t in trees])
    assert xs.max() < 100.0 + lawns.TREE_SPACING_M, "none on the open half"
    # About one per TREE_SPACING_M block over the wooded half (~100 x 200 m)
    n_blocks = (100 / lawns.TREE_SPACING_M) * (200 / lawns.TREE_SPACING_M)
    assert 0.6 * n_blocks <= len(trees) <= 1.05 * n_blocks
    assert all(lawns.TREE_RADIUS_M[0] <= t[2] <= lawns.TREE_RADIUS_M[1] for t in trees)
    # Treetops sit on high cells
    for x, y, _ in trees[:50]:
        c, r = int((x - origin[0]) / 0.5), int((origin[1] - y) / 0.5)
        assert h[r, c] > lawns.TREE_MIN_H_M


def test_canopy_trees_skip_nodata_and_lawns():
    h = np.full((200, 200), np.nan, np.float32)
    w = np.ones((50, 50), np.float32)
    assert lawns.canopy_trees(h, 0.5, (0.0, 100.0), w, 2.0) == []
    h = np.full((200, 200), 15.0, np.float32)
    assert lawns.canopy_trees(h, 0.5, (0.0, 100.0), np.zeros((50, 50), np.float32), 2.0) == []
