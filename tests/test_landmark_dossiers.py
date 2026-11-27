"""Landmark dossiers (config/landmarks/<slug>.json), Phase 0 step 4 of
docs/landmarks_plan.md.

Every number a v19 landmark model uses is written down in its dossier with a
source URL, or marked an estimate with a reason: the rule the v18 bridges
follow (tests/test_bridges.py, test_every_bridge_structure_value_...). These
tests enforce it on every dossier in config/landmarks/, check the dossier
against config/landmarks/index.json, and cover the measurement helpers in
pixelphilly.landmark_dossier that scripts/50_landmark_measure.py uses on the
2022 LiDAR and the 2024 aerial.
"""

import json

import numpy as np
import pytest

from pixelphilly import landmark_dossier as ld
from pixelphilly.projection import REPO_ROOT

PILOT = ["city_hall", "liberty_place", "lincoln_financial_field", "citizens_bank_park", "xfinity_mobile_arena",
         "art_museum", "boathouse_row", "tacony_palmyra_bridge"]


def _index():
    return {e["slug"]: e for e in json.loads((REPO_ROOT / "config" / "landmarks" / "index.json").read_text())["entries"]}


def _good(**over):
    d = {
        "slug": "test_hall", "name": "Test Hall", "wikidata": "Q1", "kit": "tower_stages",
        "about": "A synthetic dossier for the schema tests.",
        "footprint": {"polygon": [[-75.1, 39.9], [-75.0999, 39.9], [-75.0999, 39.9001], [-75.1, 39.9001], [-75.1, 39.9]],
                      "source": "https://opendataphilly.org/datasets/li-building-footprints/",
                      "replaces": {"li_footprint_ids": [1], "osm_ways": []}},
        "dims": {"height_total_m": {"value": 100.0, "unit": "m", "source": "https://example.org/a"},
                 "roof_height_m": {"value": 90.0, "unit": "m", "estimate": True, "reason": "Read off the LiDAR by eye."}},
        "colors": {"wall": {"rgb": [120, 110, 100], "source": "https://example.org/b", "method": "aerial median"}},
        "kit_params": {"stages": [{"name": "base", "top_m": {"value": 30.0, "unit": "m", "source": "https://example.org/c"}}],
                       "spire": True},
        "credits": ["Test"],
    }
    d.update(over)
    return d


_ENTRY = {"slug": "test_hall", "kit": "tower_stages", "lon": -75.09995, "lat": 39.90005}


# --- The validator on synthetic dossiers ---

def test_a_good_dossier_has_no_errors():
    assert ld.check(_good(), _ENTRY) == []


def test_a_value_without_source_or_estimate_is_an_error():
    d = _good()
    d["dims"]["height_total_m"] = {"value": 100.0, "unit": "m"}
    assert any("height_total_m" in e for e in ld.check(d, _ENTRY))


def test_a_source_must_be_a_url():
    d = _good()
    d["dims"]["height_total_m"]["source"] = "Wikipedia"
    assert ld.check(d, _ENTRY)


def test_an_estimate_needs_a_reason():
    d = _good()
    d["dims"]["roof_height_m"]["reason"] = "eh"
    assert any("roof_height_m" in e for e in ld.check(d, _ENTRY))


def test_a_bare_number_anywhere_in_dims_or_kit_params_is_an_error():
    d = _good()
    d["kit_params"]["stages"][0]["width_m"] = 12.0
    errs = ld.check(d, _ENTRY)
    assert any("width_m" in e for e in errs), errs


def test_kit_params_may_name_dims_but_the_names_must_exist():
    d = _good()
    d["kit_params"]["stages"][0]["z1_m"] = "height_total_m"
    assert ld.check(d, _ENTRY) == []
    d["kit_params"]["stages"][0]["z1_m"] = "height_totl_m"
    assert any("height_totl_m" in e for e in ld.check(d, _ENTRY))


def test_a_value_needs_a_unit():
    d = _good()
    del d["dims"]["height_total_m"]["unit"]
    assert ld.check(d, _ENTRY)


def test_colors_need_three_bytes_and_a_source():
    d = _good()
    d["colors"]["wall"]["rgb"] = [300, 0]
    assert ld.check(d, _ENTRY)
    d = _good()
    del d["colors"]["wall"]["source"]
    assert ld.check(d, _ENTRY)


def test_the_kit_must_match_the_index():
    assert ld.check(_good(kit="church"), _ENTRY)


def test_the_footprint_must_be_closed_valid_and_near_the_landmark():
    d = _good()
    d["footprint"]["polygon"] = d["footprint"]["polygon"][:-1]
    assert ld.check(d, _ENTRY)
    d = _good()
    d["footprint"]["polygon"] = [[-75.1, 39.9], [-75.0999, 39.9001], [-75.0999, 39.9], [-75.1, 39.9001], [-75.1, 39.9]]
    assert ld.check(d, _ENTRY), "a bow-tie is invalid"
    far = dict(_ENTRY, lon=-75.05)  # ~4 km away
    assert any("footprint" in e for e in ld.check(_good(), far))


def test_a_kit_missing_its_required_values_is_an_error():
    d = _good()
    del d["dims"]["height_total_m"]
    assert any("height_total_m" in e for e in ld.check(d, _ENTRY))


def test_a_footprint_may_be_several_polygons():
    d = _good()
    ring = d["footprint"]["polygon"]
    d["footprint"] = {"polygons": [ring, [[x + 0.001, y] for x, y in ring]], "source": d["footprint"]["source"],
                      "replaces": d["footprint"]["replaces"]}
    assert ld.check(d, _ENTRY) == []


# --- The real dossiers ---

def _dossiers():
    return sorted(p for p in (REPO_ROOT / "config" / "landmarks").glob("*.json")
                  if p.stem not in ("index", "selection"))


def test_the_pilot_dossiers_exist():
    have = {p.stem for p in _dossiers()}
    assert set(PILOT) <= have, sorted(set(PILOT) - have)


@pytest.mark.parametrize("path", _dossiers(), ids=lambda p: p.stem)
def test_every_dossier_value_is_sourced_or_an_estimate_with_a_reason(path):
    d = json.loads(path.read_text())
    idx = _index()
    assert d["slug"] == path.stem
    assert d["slug"] in idx, "dossier for a structure not in index.json"
    assert idx[d["slug"]]["kit"] not in ("suspension", "context")
    assert ld.check(d, idx[d["slug"]]) == []


# --- Measurement helpers ---

def test_height_stats_measure_above_the_ground_ring():
    # 0.5 m grid, origin (0, 100); ground 10 m everywhere, a 20 x 20 m block
    # 30 m tall (top 40 m) at x 40-60, y 40-60, with a 2 m mast cell at 60 m
    res = 0.5
    dsm = np.full((200, 200), 10.0, np.float32)
    dsm[80:120, 80:120] = 40.0
    dsm[99, 99] = 70.0
    grid = {"dsm": dsm, "origin": (0.0, 100.0), "res": res}
    poly = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]
    s = ld.height_stats(grid, poly)
    assert abs(s["ground_m"] - 10.0) < 1e-6
    assert abs(s["p50_m"] - 30.0) < 1e-6
    assert abs(s["max_m"] - 60.0) < 1e-6
    assert s["cells"] == 1600


def test_height_stats_ignore_nan_and_report_none_when_empty():
    dsm = np.full((10, 10), np.nan, np.float32)
    s = ld.height_stats({"dsm": dsm, "origin": (0.0, 5.0), "res": 0.5}, [(0, 0), (5, 0), (5, 5), (0, 5)])
    assert s["cells"] == 0 and s["p50_m"] is None


def test_polygon_rgb_takes_the_median_of_lit_pixels_inside():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :] = (200, 100, 50)
    img[:, :20] = (10, 10, 10)  # shadow strip inside the polygon
    img[:, 80:] = (0, 255, 0)   # outside
    poly_px = [(0, 0), (80, 0), (80, 100), (0, 100)]
    out = ld.polygon_rgb(img, poly_px, drop_dark=0.3)
    assert out["rgb"] == [200, 100, 50]
    assert out["pixels"] > 0


def test_merc_px_round_trips_and_matches_the_tile_grid():
    lon, lat = -75.163894, 39.952247  # City Hall
    px, py = ld.merc_px(np.array([lon]), np.array([lat]), 19)
    lon2, lat2 = ld.merc_lonlat(px, py, 19)
    assert abs(lon2[0] - lon) < 1e-9 and abs(lat2[0] - lat) < 1e-9
    # The cached City Hall atlas tiles span x 152666-152694, y 198561-198588
    # (data/raw/MANIFEST.json); City Hall sits inside that range
    assert 152666 <= px[0] // 256 <= 152694 and 198561 <= py[0] // 256 <= 198588


@pytest.mark.parametrize("path", _dossiers(), ids=lambda p: p.stem)
def test_sampled_colors_reproduce_from_their_photo_or_the_measure_output(path):
    # A color read from a photo names the file and box; one read from the
    # aerial names the outline in output/landmarks/measure/<slug>.json.
    # Recompute both where the inputs are on disk (they aren't in git).
    d = json.loads(path.read_text())
    measure_path = REPO_ROOT / "output" / "landmarks" / "measure" / f"{d['slug']}.json"
    measure = json.loads(measure_path.read_text()) if measure_path.exists() else None
    for name, c in d["colors"].items():
        if "photo" in c:
            f = REPO_ROOT / c["photo"]["file"]
            if f.exists():
                got = ld.photo_rgb(f, c["photo"]["box"], c["photo"].get("drop_dark", 0.25))
                assert max(abs(a - b) for a, b in zip(got, c["rgb"])) <= 1, (name, got)
        if "aerial" in c and measure is not None:
            got = ld.aerial_rgb_of(measure, c["aerial"]["outline"])
            assert got is not None and max(abs(a - b) for a, b in zip(got, c["rgb"])) <= 1, (name, got)


def test_photo_rgb_reads_a_box(tmp_path):
    from PIL import Image

    a = np.zeros((20, 20, 3), np.uint8)
    a[5:15, 5:15] = (90, 80, 70)
    Image.fromarray(a).save(tmp_path / "p.png")
    assert ld.photo_rgb(tmp_path / "p.png", (5, 5, 15, 15), 0.0) == [90, 80, 70]


def _bowl_grid():
    # 0.5 m grid, 300 x 300 m, origin (0, 300); ground 5 m. A stadium:
    # outline 40-260 x 60-240, field 100 x 50 m centered on (150, 150) with
    # its long side rotated 30 degrees from east, at 4 m (1 m below street),
    # stands at 25 m, and one 45 m canopy sector on the field's north side.
    res = 0.5
    n = 600
    x = (np.arange(n) + 0.5) * res
    X, Y = np.meshgrid(x, 300.0 - x)
    dsm = np.full((n, n), 5.0, np.float32)
    out = (X >= 40) & (X <= 260) & (Y >= 60) & (Y <= 240)
    dsm[out] = 25.0
    t = np.radians(30.0)
    u = (X - 150) * np.cos(t) + (Y - 150) * np.sin(t)
    v = -(X - 150) * np.sin(t) + (Y - 150) * np.cos(t)
    field = (np.abs(u) <= 50) & (np.abs(v) <= 25)
    dsm[field] = 4.0
    dsm[out & ~field & (v > 40) & (np.abs(u) < 30)] = 45.0
    poly = [(40.0, 60.0), (260.0, 60.0), (260.0, 240.0), (40.0, 240.0)]
    return {"dsm": dsm, "origin": (0.0, 300.0), "res": res}, poly


def test_bowl_stats_find_the_field_rectangle_and_the_stands():
    grid, poly = _bowl_grid()
    b = ld.bowl_stats(grid, poly, ground_m=5.0, field_max_m=2.0)
    f = b["field"]
    assert abs(f["length_m"] - 100) < 1.5 and abs(f["width_m"] - 50) < 1.5
    assert abs((f["bearing_deg"] % 180) - 60) < 1.0, "compass bearing of the long axis: 30 deg north of east = 60 deg"
    assert abs(f["center_local"][0] - 150) < 0.5 and abs(f["center_local"][1] - 150) < 0.5
    assert abs(f["level_m"] - (-1.0)) < 0.01
    tops = [s["p95_m"] for s in b["sectors"]]
    assert max(tops) == pytest.approx(40.0, abs=0.01) and min(tops) == pytest.approx(20.0, abs=0.01)
    assert set(b["profiles"]) == {"long_pos", "long_neg", "short_pos", "short_neg"}


def test_dome_stats_measure_the_roof_eave_crown_and_axis():
    # 0.5 m grid; ground 0; an oval-ish roof: a 120 x 80 m box rotated 20
    # degrees, eave 30 m, rising as a parabola across the short axis to 38 m,
    # plus a 10 m annex beside it that isn't roof
    res, n = 0.5, 500
    x = (np.arange(n) + 0.5) * res
    X, Y = np.meshgrid(x, 250.0 - x)
    t = np.radians(20.0)
    u = (X - 125) * np.cos(t) + (Y - 125) * np.sin(t)
    v = -(X - 125) * np.sin(t) + (Y - 125) * np.cos(t)
    dsm = np.zeros((n, n), np.float32)
    roof = (np.abs(u) <= 60) & (np.abs(v) <= 40)
    dsm[roof] = (38.0 - 8.0 * (v / 40.0) ** 2)[roof]
    dsm[(np.abs(u) <= 60) & (v < -40) & (v > -60)] = 10.0
    poly = [(10.0, 10.0), (240.0, 10.0), (240.0, 240.0), (10.0, 240.0)]
    d = ld.dome_stats({"dsm": dsm, "origin": (0.0, 250.0), "res": res}, poly, ground_m=0.0)
    assert abs(d["roof"]["length_m"] - 120) < 1.5 and abs(d["roof"]["width_m"] - 80) < 1.5
    assert abs((d["roof"]["bearing_deg"] % 180) - 70) < 1.0
    assert d["crown_m"] == pytest.approx(38.0, abs=0.2)
    assert d["eave_m"] == pytest.approx(30.0, abs=0.5)
