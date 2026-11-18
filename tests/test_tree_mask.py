"""scripts/40_build_tree_mask.py: canopy detection and the depth encoding."""

import importlib.util

import numpy as np
import pytest
from PIL import Image

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("tree_mask", REPO_ROOT / "scripts" / "40_build_tree_mask.py")
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)

TILES = REPO_ROOT / "output" / "philly" / "tiles" / "v18" / "map_files" / "17"

GRASS = (112, 140, 92)      # dull lawn green: saturation about 0.34
CANOPY_A = (46, 118, 34)    # saturated leaf green
CANOPY_B = (74, 156, 44)    # sunlit leaf green
OUTLINE = (8, 20, 10)       # the 1 px near-black edge the model draws around canopies
PARK_CROWN = (82, 116, 60)  # a yellower crown, as in Fairmount Park: lawn-like color
TURF = (70, 140, 50)        # saturated, cool artificial turf: canopy color, but flat and unoutlined


def grass(h=128, w=128):
    rng = np.random.default_rng(0)
    img = np.empty((h, w, 3), np.uint8)
    img[:] = GRASS
    # Lawns carry a little noise; it must stay well under the saturation cut
    img = np.clip(img.astype(int) + rng.integers(-4, 5, img.shape), 0, 255).astype(np.uint8)
    return img


def paint_tree(img, cy, cx, r, colors=(CANOPY_A, CANOPY_B)):
    """A textured canopy disk with a dark 1 px outline, as the model draws them."""
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    dist = np.hypot(yy - cy, xx - cx)
    inside = dist < r
    img[inside] = colors[0]
    img[inside & ((yy // 2 + xx // 2) % 2 == 0)] = colors[1]
    ring = (dist >= r) & (dist < r + 1)
    img[ring] = OUTLINE
    return inside | ring


def test_threshold_alone_accepts_canopy_colors_and_rejects_grass():
    px = np.array([[CANOPY_A, CANOPY_B, GRASS, (200, 200, 200), (40, 60, 160)]], np.uint8)
    assert tm.canopy_threshold(px).tolist() == [[True, True, False, False, False]]


def test_mask_catches_a_canopy_disk_with_its_outline_and_leaves_grass():
    img = grass()
    tree = paint_tree(img, 64, 64, 14)
    m = tm.canopy_mask(img)
    assert m[tree].mean() > 0.97  # outline included
    yy, xx = np.mgrid[:128, :128]
    # Growth can slip a few px past the outline into lawn, never further
    away = np.hypot(yy - 64, xx - 64) > 14 + 1 + tm.GROW_PX + tm.OUTLINE_PX
    assert not m[away].any()


def test_flat_grass_tile_gives_no_canopy():
    assert not tm.canopy_mask(grass()).any()


def test_yellower_crown_is_caught_by_its_outline():
    img = grass()
    tree = paint_tree(img, 64, 64, 12, colors=(PARK_CROWN, PARK_CROWN))
    assert not tm.canopy_threshold(img)[56:72, 56:72].any()  # color alone misses the inside
    m = tm.canopy_mask(img)
    assert m[tree].mean() > 0.97
    assert m.sum() < tree.sum() * 1.3


def test_flat_turf_is_rejected_but_a_tree_beside_it_is_kept():
    img = grass()
    img[10:60, 10:118] = TURF  # a field: canopy-colored, no outline
    tree = paint_tree(img, 95, 64, 12)
    m = tm.canopy_mask(img)
    assert tm.canopy_threshold(img)[20:50, 20:100].all()  # the color test alone takes the turf
    assert not m[12:58, 12:116].any()
    assert m[tree].mean() > 0.97


def test_small_speckle_is_removed():
    img = grass()
    rng = np.random.default_rng(3)
    # Scattered single pixels and 2x2 dots of canopy color, the speckle seen in park lawns
    for _ in range(60):
        y, x = rng.integers(2, 126, 2)
        img[y, x] = CANOPY_A
    for _ in range(15):
        y, x = rng.integers(2, 124, 2)
        img[y:y + 2, x:x + 2] = CANOPY_B
    assert not tm.canopy_mask(img).any()


def test_depth_of_a_vertical_run():
    m = np.zeros((40, 3), bool)
    m[10:21, 1] = True  # one run, bottom at y = 20
    d = tm.depth_from_mask(m)
    assert d[20, 1] == tm.TRUNK_PX
    assert d[10, 1] == 20 - 10 + tm.TRUNK_PX
    assert d[15, 1] == 20 - 15 + tm.TRUNK_PX
    assert (d[~m] == 0).all()
    assert d.dtype == np.uint8


def test_depth_treats_separate_runs_separately_and_clamps():
    m = np.zeros((600, 1), bool)
    m[5:10, 0] = True
    m[12:15, 0] = True
    m[100:500, 0] = True
    d = tm.depth_from_mask(m)[:, 0]
    assert d[5] == 9 - 5 + tm.TRUNK_PX  # the gap at 10-11 ends the first run
    assert d[12] == 14 - 12 + tm.TRUNK_PX
    assert d[100] == 255  # 399 + 4 clamps
    assert d[499] == tm.TRUNK_PX


def make_world(trees, ntx=3, nty=3):
    """Fake tile source: a grass world with trees at (y, x, r) in world px."""
    world = grass(nty * 512, ntx * 512)
    for y, x, r in trees:
        paint_tree(world, y, x, r)
    return world, lambda tx, ty: (world[ty * 512:(ty + 1) * 512, tx * 512:(tx + 1) * 512]
                                  if 0 <= tx < ntx and 0 <= ty < nty else None)


def test_depth_run_continues_into_the_tile_below():
    # A canopy centered 6 px above the boundary between tile rows 0 and 1
    world, get = make_world([(512 - 6, 700, 20)])
    ref = tm.depth_from_mask(tm.canopy_mask(world))  # the whole world at once: no tile edges
    d = tm.tile_depth(get, 1, 0)
    col = 700 - 512
    run = np.flatnonzero(ref[:, 700])
    bottom = run.max()
    assert bottom > 512 + 10  # the run really does cross into the tile below
    for y in (490, 500, 511):
        assert d[y, col] == bottom - y + tm.TRUNK_PX, y
    assert (d == ref[:512, 512:1024]).all()
    below = tm.tile_depth(get, 1, 1)
    assert below[bottom - 512, col] == tm.TRUNK_PX
    assert (below == ref[512:1024, 512:1024]).all()


def test_canopy_crossing_a_side_edge_is_kept_whole():
    world, get = make_world([(700, 512 + 3, 16)])
    left, right = tm.tile_depth(get, 0, 1), tm.tile_depth(get, 1, 1)
    joined = np.concatenate([left, right], axis=1)
    m = paint_tree(np.zeros((1536, 1536, 3), np.uint8), 700, 515, 16)[512:1024, :1024]
    assert (joined[m] > 0).mean() > 0.97


def test_empty_tiles_are_not_written(tmp_path):
    _, get = make_world([(200, 200, 15)])
    assert tm.write_tile(tmp_path, 0, 0, tm.tile_depth(get, 0, 0)) is True
    assert tm.write_tile(tmp_path, 2, 2, tm.tile_depth(get, 2, 2)) is False
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["0_0.png"]
    png = Image.open(tmp_path / "0_0.png")
    assert png.mode == "L" and png.size == (512, 512)


@pytest.mark.skipif(not (TILES / "104_121.png").exists() and not (TILES / "104_121.webp").exists(),
                    reason="v18 tiles not on this machine")
def test_real_tile_rittenhouse_square_has_canopy_but_is_not_all_canopy():
    # Rittenhouse Square, map px (53495, 62215): tree-lined paths around a lawn
    d = tm.tile_depth(tm.load_tile, 53495 // 512, 62215 // 512)
    share = (d > 0).mean()
    assert 0.05 < share < 0.8, share
