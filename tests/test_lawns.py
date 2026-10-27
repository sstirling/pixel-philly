"""Dormant lawns in the leaf-off aerial: shift brown grass toward green inside
park polygons, nothing else."""

import numpy as np

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
