"""Mapped water bodies the river color model misses (waterpaint.body_models,
body_water). The Manayunk Canal is in the City (PWD) water layer, not in
NHD, and its olive-green water doesn't match the brown river, so it was drawn
as grass (Nov. 4). Each PWD-only polygon gets its own color model."""

import numpy as np
from shapely.geometry import Polygon, box

from pixelphilly import waterpaint

RIVER = (110, 95, 70)
CANAL = (95, 105, 60)
LAWN = (90, 140, 60)
PAVING = (170, 168, 160)
BOAT = (230, 230, 235)


def _scene():
    img = np.zeros((200, 300, 3), np.uint8)
    img[:] = LAWN
    img[:60, :] = RIVER  # river, in NHD
    img[100:130, :] = CANAL  # canal, PWD only
    img[110:118, 140:160] = BOAT  # a boat in the canal
    rng = np.random.default_rng(0)
    img = np.clip(img.astype(int) + rng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
    nhd = box(0, 0, 300, 60)
    canal = box(0, 100, 300, 130)
    mixed = box(0, 160, 300, 200)  # a "water" polygon over lawn and paving (a dry basin)
    img[160:200, 150:] = PAVING
    return img, nhd, [canal, mixed]


def _reader(img):
    def region(gx, gy, w, h):
        out = np.zeros((h, w, 3), np.uint8)
        x0, y0 = max(gx, 0), max(gy, 0)
        x1, y1 = min(gx + w, img.shape[1]), min(gy + h, img.shape[0])
        if x0 < x1 and y0 < y1:
            out[y0 - gy:y1 - gy, x0 - gx:x1 - gx] = img[y0:y1, x0:x1]
        return out
    return region


def test_canal_gets_its_own_color_model_and_dry_basin_is_skipped():
    img, nhd, pwd = _scene()
    views = [(0, 0, img[:, :150], None), (150, 0, img[:, 150:], None)]  # two "frames"
    models = waterpaint.body_models(pwd, nhd, views)
    assert len(models) == 1, "the mixed lawn/paving polygon isn't a water surface"
    poly, median, threshold = models[0]
    assert np.abs(np.asarray(median) - CANAL).max() < 8
    water = waterpaint.body_water(models, img, np.zeros(img.shape[:2], bool), 0, 0)
    assert water[105:125, 20:120].mean() > 0.95  # the canal
    assert not water[112:116, 145:155].any()  # the boat stays drawn
    assert not water[60:100].any() and not water[135:].any()  # lawn, the dry basin
    assert not water[:60].any()  # the river is left to the NHD model


def test_no_bodies_no_water():
    img, nhd, _ = _scene()
    assert waterpaint.body_models([], nhd, [(0, 0, img, None)]) == []
    assert not waterpaint.body_water([], img, np.zeros(img.shape[:2], bool), 0, 0).any()


def test_polygon_inside_nhd_is_left_to_the_river_model():
    img, nhd, _ = _scene()
    assert waterpaint.body_models([Polygon([(10, 10), (100, 10), (100, 50), (10, 50)])], nhd, [(0, 0, img, None)]) == []


def test_tree_discs_mask_rendered_canopies():
    # A creek polygon under tree canopies (roxborough woods_trees) must not
    # learn canopy green as its water color, nor repaint canopies as water
    from pixelphilly.projection import IsoCamera

    cam = IsoCamera(54, 45, 0.293)
    trees = [[0.0, 0.0, 4.0], [100.0, 0.0, 2.0]]
    discs = waterpaint.tree_discs(trees, cam, 0.0, 0.0)
    assert len(discs) == 2 and abs(discs[0][2] - 4.0 / 0.293) < 1e-6
    sx, sy, r = discs[0]
    m = waterpaint.tree_mask(discs, int(sx) - 40, int(sy) - 40, 80, 80)
    assert m[40, 40] and not m[0, 0]
    assert abs(m.sum() - np.pi * r * r) / (np.pi * r * r) < 0.1
