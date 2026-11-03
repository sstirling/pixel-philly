"""Clean (self-distilled) training set: filters, terrain classes, held-out
exclusion and provenance (pixelphilly.trainset_clean)."""

import numpy as np
import pytest
from shapely.geometry import box

from pixelphilly import trainset_clean as tc


# --- filters ------------------------------------------------------------------
def test_shift_ok_accepts_up_to_two_px():
    assert tc.shift_ok((0, 0)) and tc.shift_ok((2, -2))
    assert not tc.shift_ok((3, 0)) and not tc.shift_ok((0, -5))


def test_invented_color_share_ignores_color_the_render_has():
    render = np.full((60, 60, 3), 120, np.uint8)
    render[10:20, 10:20] = (200, 30, 30)  # a red roof in the render
    target = render.copy()
    assert tc.invented_color_share(render, target) == 0.0
    target[40:44, 40:46] = (30, 60, 220)  # a blue "car" on gray pavement
    share = tc.invented_color_share(render, target)
    assert share == pytest.approx(24 / 3600)


def test_invented_color_share_ignores_dull_color():
    render = np.full((40, 40, 3), 120, np.uint8)
    target = render.copy()
    target[5:15, 5:15] = (140, 120, 110)  # low saturation: brick shade, not a car
    assert tc.invented_color_share(render, target) == 0.0


def test_tone_delta_is_mean_luminance_and_chroma_shift():
    render = np.full((10, 10, 3), 100, np.uint8)
    target = np.full((10, 10, 3), 130, np.uint8)
    d = tc.tone_delta(render, target)
    assert d["dlum"] == pytest.approx(30.0)
    assert d["drg"] == pytest.approx(0.0) and d["dyb"] == pytest.approx(0.0)


def test_robust_outliers_flags_only_the_far_value():
    vals = [0.0, 1.0, -1.0, 0.5, -0.5, 0.2, 40.0]
    out = tc.robust_outliers(vals, k=3.5)
    assert out == [False] * 6 + [True]


def test_robust_outliers_with_no_spread_flags_nothing_equal():
    assert tc.robust_outliers([1.0, 1.0, 1.0]) == [False, False, False]


def test_evaluate_collects_every_reason():
    scores = {"shift": [5, 0], "flat_share": 0.1, "invented_water_blobs": 2, "invented_color_share": 0.5,
              "tone_outlier": True}
    reasons = tc.reject_reasons(scores, flat_range=(0.22, 0.6), max_color=0.012)
    assert len(reasons) == 5
    ok = {"shift": [0, 1], "flat_share": 0.4, "invented_water_blobs": 0, "invented_color_share": 0.004,
          "tone_outlier": False}
    assert tc.reject_reasons(ok, flat_range=(0.22, 0.6), max_color=0.012) == []


# --- terrain classes ----------------------------------------------------------
BASE = dict(building_share=0.3, water_share=0.0, park_share=0.0, green_share=0.05, median_footprint_m2=80.0,
            max_height_m=12.0, tags=())


@pytest.mark.parametrize("over,label", [
    ({}, "rowhouse"),
    ({"max_height_m": 120.0}, "tower"),
    ({"water_share": 0.4}, "river"),
    ({"water_share": 0.95}, "open_water"),
    ({"park_share": 0.6, "building_share": 0.02, "green_share": 0.4}, "park"),
    ({"park_share": 0.6, "building_share": 0.02, "green_share": 0.05}, "woods"),
    ({"median_footprint_m2": 2500.0}, "industrial"),
    ({"median_footprint_m2": 650.0}, "industrial"),
    ({"median_footprint_m2": 400.0}, "rowhouse"),
    ({"tags": ("stadium",)}, "stadium"),
    ({"tags": ("port",), "water_share": 0.3}, "port"),
    ({"building_share": 0.01}, "open"),
])
def test_classify_terrain(over, label):
    assert tc.classify_terrain({**BASE, **over}) == label


def test_stratified_pick_respects_quotas_and_is_deterministic():
    items = [{"id": f"r{i}", "terrain": "rowhouse"} for i in range(50)] + \
            [{"id": f"t{i}", "terrain": "tower"} for i in range(3)]
    a = tc.stratified_pick(items, {"rowhouse": 10, "tower": 5}, seed=1)
    b = tc.stratified_pick(items, {"rowhouse": 10, "tower": 5}, seed=1)
    assert [x["id"] for x in a] == [x["id"] for x in b]
    assert sum(x["terrain"] == "rowhouse" for x in a) == 10
    assert sum(x["terrain"] == "tower" for x in a) == 3  # fewer available than the quota
    assert all(x["terrain"] in ("rowhouse", "tower") for x in a)


# --- held-out exclusion -------------------------------------------------------
def test_frames_near_eval_spots_are_excluded():
    eval_polys = [box(1000, 1000, 1500, 1500)]
    assert tc.near_eval((0, 0, 1024), eval_polys, margin_px=0) is True    # overlaps
    assert tc.near_eval((2600, 0, 1024), eval_polys, margin_px=0) is False
    assert tc.near_eval((1600, 1600, 1024), eval_polys, margin_px=200) is True  # inside the margin
    assert tc.near_eval((1600, 1600, 1024), eval_polys, margin_px=50) is False


# --- provenance ---------------------------------------------------------------
def test_provenance_check_rejects_any_gemini_trace():
    good = {"id": "x", "target_model": "Qwen/Qwen-Image-Edit-2511@6f3c", "source_render": "output/a/renders/f.png"}
    tc.check_provenance(good)
    for bad in ({**good, "target_model": "gemini-3-pro-image"},
                {**good, "source_render": "output/oldcity/trainset/target/x.png"},
                {**good, "style": "/runs/lora/qe2511_oldcity_r16_v1/x.safetensors"},
                {**good, "origin": "output/a/redraws/redraw_v3/f.png"}):
        with pytest.raises(ValueError):
            tc.check_provenance(bad)


# --- masked scores, featureless input, seed choice -----------------------------
def test_flat_share_masked_ignores_masked_pixels():
    from pixelphilly.qa import flat_share
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (40, 40, 3)).astype(np.uint8)  # noisy: nothing flat
    img[:, 20:] = 90  # right half flat
    keep = np.zeros((40, 40), bool)
    keep[:, :18] = True
    assert tc.flat_share_masked(img, keep) == 0.0
    keep_all = np.ones((40, 40), bool)
    assert tc.flat_share_masked(img, keep_all) == pytest.approx(flat_share(img), abs=1e-9)


def test_featureless_share_finds_the_no_data_gray():
    rng = np.random.default_rng(1)
    img = rng.integers(60, 200, (50, 50, 3)).astype(np.uint8)
    img[:25] = (128, 128, 128)
    share = tc.featureless_share(img)
    assert 0.40 < share < 0.5  # interior rows only: 23 x 48 of 2,500
    assert tc.featureless_share(rng.integers(60, 200, (50, 50, 3)).astype(np.uint8)) == 0.0


def test_first_passing_seed_is_kept():
    tries = {0: ["invented color"], 1: [], 2: []}
    assert tc.first_passing(tries) == 1
    assert tc.first_passing({0: ["x"], 1: ["y"]}) is None


def test_views_mostly_on_no_data_ground_are_rejected():
    ok = {"shift": [0, 0], "flat_share": 0.4, "invented_water_blobs": 0, "invented_color_share": 0.0,
          "tone_outlier": False, "featureless_share": 0.5}
    assert tc.reject_reasons(ok, (0.26, 0.72), 0.012)[0].startswith("no-data ground")


def test_flat_white_roofs_are_not_no_data():
    rng = np.random.default_rng(2)
    img = rng.integers(60, 200, (50, 50, 3)).astype(np.uint8)
    img[:25] = (236, 236, 234)  # a big white warehouse roof
    assert tc.featureless_share(img) == 0.0


# --- speck clean-up (cars, confetti) ------------------------------------------
def _street(seed=3):
    rng = np.random.default_rng(seed)
    return np.clip(110 + rng.integers(-4, 5, (80, 80, 1)), 0, 255).repeat(3, axis=2).astype(np.uint8)


def test_remove_specks_paints_a_car_with_the_street():
    render = _street()
    target = render.copy()
    target[30:34, 30:36] = (200, 30, 30)  # red car on gray asphalt
    out, n = tc.remove_invented_specks(render, target)
    assert n >= 24
    assert tc.invented_color_share(render, out) == 0.0
    assert np.abs(out[30:34, 30:36].astype(int) - 110).max() <= 8


def test_remove_specks_keeps_green_trees_and_render_colors():
    render = _street()
    render[5:15, 5:15] = (190, 60, 50)  # a red roof in the render
    target = render.copy()
    target[50:58, 50:58] = (40, 160, 50)  # a green tree on brown/gray: allowed
    out, n = tc.remove_invented_specks(render, target)
    assert n == 0 and np.array_equal(out, target)
    assert tc.invented_color_share(render, target) == 0.0


def test_near_copies_of_the_render_are_rejected():
    s = {"shift": [0, 0], "flat_share": 0.4, "invented_water_blobs": 0, "invented_color_share": 0.0,
         "tone_outlier": False, "mean_abs_diff": 6.0}
    assert any(r.startswith("near-copy") for r in tc.reject_reasons(s, (0.26, 0.72), 0.012, min_diff=13))
    s["mean_abs_diff"] = 20.0
    assert tc.reject_reasons(s, (0.26, 0.72), 0.012, min_diff=13) == []
