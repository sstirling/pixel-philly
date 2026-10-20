import pytest

from pixelphilly.heights import FT_TO_M, building_height


def test_approx_height_wins():
    h, src, out = building_height(40, 45, 10.0, 3.0)
    assert h == pytest.approx(40 * FT_TO_M)
    assert src == "approx_hgt" and not out


def test_one_dock_st_conflict_is_flagged_not_inflated():
    # 1 Dock St in the city layer: approx_hgt 50 ft, max_hgt 368.63 ft
    h, src, out = building_height(50, 368.63014825000005, 10.0, 3.0)
    assert h == pytest.approx(50 * FT_TO_M)
    assert src == "approx_hgt"
    assert out


def test_falls_back_to_max_then_default():
    assert building_height(None, 30, 10.0, 3.0)[:2] == (pytest.approx(30 * FT_TO_M), "max_hgt")
    assert building_height(0, None, 10.0, 3.0)[:2] == (10.0, "default")
    assert building_height(None, None, 10.0, 3.0)[:2] == (10.0, "default")
