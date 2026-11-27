"""Phase D comparison and blind review (scripts/47_era_compare.py;
docs/building_age_plan.md)."""

import importlib.util
import json

import numpy as np
import pytest

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("era_compare", REPO_ROOT / "scripts" / "47_era_compare.py")
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)


def _imgs(shape=(64, 64)):
    rng = np.random.default_rng(0)
    base = rng.integers(60, 200, (*shape, 3)).astype(float)
    return base


def test_retention_full_partial_and_none():
    r_old = _imgs()
    r_new = r_old.copy()
    r_new[10:30, 10:30] -= 40  # the render got darker here
    bld = np.ones(r_old.shape[:2], bool)
    d_old = r_old + 5
    full = ec.step_retention(r_old, r_new, d_old, d_old + (r_new - r_old), bld)
    half = ec.step_retention(r_old, r_new, d_old, d_old + 0.5 * (r_new - r_old), bld)
    none = ec.step_retention(r_old, r_new, d_old, d_old, bld)
    assert full["retention"] == pytest.approx(1.0)
    assert half["retention"] == pytest.approx(0.5)
    assert none["retention"] == pytest.approx(0.0)
    assert full["changed_px"] == 400
    assert full["followed_share"] == pytest.approx(1.0) and none["followed_share"] == 0.0
    # Elsewhere on buildings nothing moved
    assert full["noise_share"] == 0.0


def test_retention_noise_share_counts_only_far_building_pixels():
    r_old = _imgs()
    r_new = r_old.copy()
    r_new[0:10, 0:10] += 50
    d_old = r_old.copy()
    d_new = d_old.copy()
    d_new[40:50, 40:50] += 50  # a change the render didn't ask for
    bld = np.zeros(r_old.shape[:2], bool)
    bld[30:64, 30:64] = True
    out = ec.step_retention(r_old, r_new, d_old, d_new, bld)
    assert out["noise_share"] == pytest.approx(100 / bld.sum())


def test_retention_by_label():
    r_old = _imgs()
    r_new = r_old.copy()
    r_new[:, :32] -= 40
    d_old = r_old.copy()
    d_new = d_old.copy()
    d_new[:, :16] -= 40  # label 1 kept, label 2 not
    labels = np.zeros(r_old.shape[:2], int)
    labels[:, :16] = 1
    labels[:, 16:32] = 2
    out = ec.retention_by_label(r_old, r_new, d_old, d_new, labels, {1: "one", 2: "two"})
    assert out["one"]["retention"] == pytest.approx(1.0)
    assert out["two"]["retention"] == pytest.approx(0.0)


def test_stratified_sample_covers_rare_strata_and_is_stable():
    items = [{"id": i, "stratum": "common"} for i in range(200)] + [{"id": 1000 + i, "stratum": "rare"}
                                                                     for i in range(3)]
    a = ec.stratified_sample(items, 20, seed=1)
    b = ec.stratified_sample(items, 20, seed=1)
    assert [x["id"] for x in a] == [x["id"] for x in b]
    assert len(a) == 20
    assert sum(x["stratum"] == "rare" for x in a) == 3
    assert ec.stratified_sample(items[:5], 20, seed=1) == ec.stratified_sample(items[:5], 20, seed=1)
    assert len(ec.stratified_sample(items[:5], 20, seed=1)) == 5


def test_blinding_hides_which_side_is_which():
    items = [{"id": f"x{i}"} for i in range(40)]
    order, key = ec.blind(items, seed=3)
    assert sorted(k for k in key) == sorted(o["rid"] for o in order)
    sides = [key[o["rid"]]["left"] for o in order]
    assert set(sides) == {"base", "era"}
    assert 10 < sides.count("era") < 30
    # The review page's records carry only opaque ids, never the variant
    assert all(set(o) == {"rid"} for o in order)


def test_score_unblinds():
    key = {"r1": {"left": "era", "spot": "s", "stratum": "a"}, "r2": {"left": "base", "spot": "s", "stratum": "a"},
           "r3": {"left": "era", "spot": "t", "stratum": "b"}, "r4": {"left": "base", "spot": "t", "stratum": "b"}}
    review = {"scores": {"r1": "left", "r2": "left", "r3": "same", "r4": "neither"}}
    out = ec.score(review, key)
    assert out["all"] == {"era_better": 1, "base_better": 1, "same": 1, "neither_right": 1, "unscored": 0}
    assert out["by_spot"]["s"]["era_better"] == 1 and out["by_spot"]["s"]["base_better"] == 1
    assert out["by_stratum"]["b"]["same"] == 1


def test_review_page_has_no_variant_names(tmp_path):
    from PIL import Image

    img = Image.new("RGB", (8, 8), (10, 20, 30))
    items = [{"rid": "r001", "spot_label": "Test spot", "aerial": img, "left": img, "right": img}]
    path = tmp_path / "index.html"
    ec.write_review_page(items, path)
    page = path.read_text()
    assert "r001" in page
    for word in ("qwen_joint", "eraC", "_eb", "baseline"):
        assert word not in page
    assert "<title>" in page and "localStorage" in page


def test_roof_classes_share_the_sample_before_eras():
    items = ([{"id": i, "roof": "flat", "era": f"e{i % 6}"} for i in range(300)]
             + [{"id": 1000 + i, "roof": "front_slope", "era": "postwar"} for i in range(50)]
             + [{"id": 2000 + i, "roof": "fitted", "era": "postwar"} for i in range(4)])
    got = ec.roof_then_era_sample(items, 20, seed=2)
    roofs = [g["roof"] for g in got]
    assert roofs.count("fitted") == 4 and roofs.count("front_slope") == 8 and roofs.count("flat") == 8
    assert len({g["era"] for g in got if g["roof"] == "flat"}) == 6
    assert all(g["stratum"] == f"{g['era']}/{g['roof']}" for g in got)
