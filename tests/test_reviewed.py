"""Reviewed data corrections applied in the scene build
(pixelphilly.reviewed): height overrides for footprints whose City height
is a data error, and footprints excluded from the stadium (seating-row)
rule."""

import json

import pytest

from pixelphilly import reviewed
from pixelphilly.projection import REPO_ROOT
from pixelphilly.qa_scan import find_needles


def _sq(x, y, s):
    return [[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]]


def _scrapyard():
    """A 6 x 6 m 'tank' recorded at 42 m among 6-10 m sheds and a 9 m
    warehouse (5458 Tacony St: 38 m², City record 138 ft)."""
    bs = [{"id": 478499, "h": 42.06, "polys": [_sq(0, 0, 6)], "ceiling_m": 42.5, "typical_m": 42.06}]
    for k, (x, y, h) in enumerate([(12, 0, 6.0), (-16, 0, 8.0), (0, 14, 10.0), (0, -20, 9.0)]):
        bs.append({"id": 1000 + k, "h": h, "polys": [_sq(x, y, 8)], "ceiling_m": h, "typical_m": h})
    bs.append({"id": 2000, "h": 30.0, "polys": [_sq(300, 300, 20)]})  # far away: not a neighbor
    return bs


OVR = {"478499": {"id": 478499, "mode": "neighbor", "reason": "r", "source": "s", "reviewed": "2026-11-02"}}


def test_neighbor_override_takes_the_surroundings_height():
    bs = _scrapyard()
    qa = reviewed.apply_height_overrides(bs, OVR, default_m=10.0)
    b = bs[0]
    assert b["h"] == pytest.approx(8.5)  # median of 6, 8, 9, 10 (within NEIGHBOR_RADIUS_M)
    # LiDAR shaping and its noise ceiling mustn't bring the bad height back
    assert b["height_override"] and b["ceiling_m"] is None and b["typical_m"] is None
    assert qa == [{"id": 478499, "mode": "neighbor", "from_m": 42.06, "to_m": 8.5, "neighbors": 4}]
    assert [x["h"] for x in bs[1:]] == [6.0, 8.0, 10.0, 9.0, 30.0]


def test_needle_scan_passes_on_the_fixed_data():
    bs = _scrapyard()
    assert [n["id"] for n in find_needles(bs)] == [478499]
    reviewed.apply_height_overrides(bs, OVR, default_m=10.0)
    assert find_needles(bs) == []


def test_meters_override_and_fallback_without_neighbors():
    bs = _scrapyard()
    reviewed.apply_height_overrides(bs, {"2000": {"id": 2000, "mode": "meters", "meters": 12.0}}, default_m=10.0)
    assert bs[-1]["h"] == 12.0
    lone = [{"id": 5, "h": 50.0, "polys": [_sq(0, 0, 5)]}]
    qa = reviewed.apply_height_overrides(lone, {"5": {"id": 5, "mode": "neighbor"}}, default_m=10.0)
    assert lone[0]["h"] == 10.0 and qa[0]["neighbors"] == 0


def test_no_overrides_changes_nothing():
    bs = _scrapyard()
    before = json.dumps(bs)
    assert reviewed.apply_height_overrides(bs, {}, default_m=10.0) == []
    assert json.dumps(bs) == before


def test_bad_mode_is_refused():
    with pytest.raises(ValueError):
        reviewed.apply_height_overrides(_scrapyard(), {"478499": {"id": 478499, "mode": "guess"}}, default_m=10.0)


def test_load_keys_by_string_id(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"entries": [{"id": 478499, "mode": "neighbor"}, {"id": "s12", "mode": "meters",
                                                                               "meters": 5}]}))
    got = reviewed.load(p)
    assert set(got) == {"478499", "s12"}
    assert reviewed.load(tmp_path / "missing.json") == {}


def test_stadium_exclusion():
    ex = {"386385": {"id": 386385}}
    assert reviewed.stadium_excluded(386385, ex) and reviewed.stadium_excluded("386385", ex)
    assert not reviewed.stadium_excluded(1262, ex)


@pytest.mark.parametrize("name", ["height_overrides.json", "stadium_exclusions.json"])
def test_reviewed_files_are_documented(name):
    # Every entry says what was checked, where, and when
    data = json.loads((REPO_ROOT / "config" / name).read_text())
    assert data["entries"]
    for e in data["entries"]:
        assert e["id"] and e["reason"] and e["source"] and e["reviewed"], e
        if name == "height_overrides.json":
            assert e["mode"] in reviewed.MODES
