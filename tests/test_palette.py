"""v2 targets: a palette from our own renders, dither-free snapping and
connected-component speck removal (pixelphilly.palette)."""

import numpy as np
import pytest

from pixelphilly import palette as pal


def _two_tone(seed=0):
    rng = np.random.default_rng(seed)
    a = np.zeros((60, 60, 3), np.uint8)
    a[:, :30] = (150, 82, 62)  # brick
    a[:, 30:] = (110, 110, 112)  # asphalt
    return np.clip(a.astype(int) + rng.integers(-6, 7, a.shape), 0, 255).astype(np.uint8)


def test_build_palette_is_deterministic_and_sized():
    samples = [_two_tone(0), _two_tone(1)]
    p1 = pal.build_palette(samples, k=8, seed=0)
    p2 = pal.build_palette(samples, k=8, seed=0)
    assert p1.shape == (8, 3) and p1.dtype == np.uint8
    assert np.array_equal(p1, p2)


def test_build_palette_finds_the_main_colors():
    p = pal.build_palette([_two_tone(0)], k=2, seed=0)
    d = lambda c: np.abs(p.astype(int) - np.array(c)).sum(axis=1).min()  # noqa: E731
    assert d((150, 82, 62)) < 15 and d((110, 110, 112)) < 15


def test_snap_uses_only_palette_colors_and_no_dither():
    p = np.array([[0, 0, 0], [255, 255, 255], [200, 30, 30]], np.uint8)
    img = np.full((20, 20, 3), 128, np.uint8)  # mid gray: a ditherer would checkerboard it
    out, idx = pal.snap(img, p)
    colors = {tuple(c) for c in out.reshape(-1, 3)}
    assert colors <= {tuple(c) for c in p}
    assert len(colors) == 1  # no dither pattern
    assert idx.shape == (20, 20)


def test_remove_specks_clears_a_cluster_of_cars_on_asphalt():
    p = np.array([[110, 110, 112], [200, 30, 30], [30, 60, 200], [240, 240, 240]], np.uint8)
    render = np.full((80, 80, 3), (110, 110, 112), np.uint8)
    idx = np.zeros((80, 80), np.int32)
    # a parking lot full of cars: many small red/blue/white blobs, touching rows
    for i, y in enumerate(range(10, 70, 6)):
        for j, x in enumerate(range(10, 70, 7)):
            idx[y:y + 3, x:x + 5] = 1 + (i + j) % 3
    out = pal.remove_specks(idx, p, render, max_px=40)
    assert (out == 0).mean() > 0.99


def test_remove_specks_keeps_small_details_the_render_has():
    p = np.array([[110, 110, 112], [200, 30, 30]], np.uint8)
    render = np.full((40, 40, 3), (110, 110, 112), np.uint8)
    render[10:14, 10:14] = (200, 30, 30)  # a small red roof really there
    idx = np.zeros((40, 40), np.int32)
    idx[10:14, 10:14] = 1
    out = pal.remove_specks(idx, p, render, max_px=40)
    assert (out[10:14, 10:14] == 1).all()


def test_remove_specks_keeps_large_regions():
    p = np.array([[110, 110, 112], [200, 30, 30]], np.uint8)
    render = np.full((40, 40, 3), (110, 110, 112), np.uint8)
    idx = np.zeros((40, 40), np.int32)
    idx[5:25, 5:25] = 1  # 400 px: a big red roof the model drew, not a speck
    out = pal.remove_specks(idx, p, render, max_px=40)
    assert (out[5:25, 5:25] == 1).all()


def test_dark_and_white_specks_go_too_when_the_render_lacks_them():
    p = np.array([[110, 110, 112], [20, 20, 22], [245, 245, 245]], np.uint8)
    render = np.full((40, 40, 3), (110, 110, 112), np.uint8)
    idx = np.zeros((40, 40), np.int32)
    idx[5:8, 5:10] = 1   # dark car
    idx[20:23, 20:25] = 2  # white car
    out = pal.remove_specks(idx, p, render, max_px=40)
    assert (out == 0).all()


def test_thin_lines_survive_speck_removal():
    # 1-2 px lines (window mullions, lane markings, outlines) are drawing
    # detail even when short and absent from the render
    p = np.array([[110, 110, 112], [20, 20, 22], [245, 245, 245]], np.uint8)
    render = np.full((40, 40, 3), (110, 110, 112), np.uint8)
    idx = np.zeros((40, 40), np.int32)
    idx[5:25, 10] = 1        # 20 px dark vertical line, 1 px wide
    idx[30, 5:30] = 2        # 25 px white lane line
    idx[12:14, 20:35] = 1    # 2 px wide dark band
    out = pal.remove_specks(idx, p, render, max_px=40)
    assert np.array_equal(out, idx)
