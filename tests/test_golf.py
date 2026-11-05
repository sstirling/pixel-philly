"""Golf courses (Nov. 3, Stephen): OSM courses and golf features, the golf
lawn band, water hazards. Synthetic Overpass JSON and pixels."""

import colorsys

import numpy as np

from pixelphilly import golf, lawns
from pixelphilly.invented_water import _hsv


def _way(i, tags, coords):
    return {"type": "way", "id": i, "tags": tags, "geometry": [{"lon": x, "lat": y} for x, y in coords]}


def _sq(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


ELEMENTS = [
    _way(1, {"leisure": "golf_course", "name": "Byrne"}, _sq(0, 0, 0.01)),
    _way(2, {"disused:leisure": "golf_course", "name": "Karakung"}, _sq(1, 1, 0.01)),
    _way(3, {"leisure": "golf_course", "name": "Strawberry Green Driving Range"}, _sq(2, 2, 0.002)),
    _way(4, {"leisure": "golf_course", "name": "Cobbs Creek Golf Course Olde"}, _sq(3, 3, 0.01)),
    _way(10, {"golf": "fairway"}, _sq(0.001, 0.001, 0.003)),
    _way(11, {"golf": "bunker"}, _sq(0.005, 0.005, 0.0005)),
    _way(12, {"golf": "water_hazard"}, _sq(0.007, 0.007, 0.001)),
    _way(13, {"golf": "cartpath"}, [(0, 0), (0.01, 0.01)]),  # a line: ignored
    {"type": "relation", "id": 20, "tags": {"golf": "rough"},
     "members": [{"type": "way", "role": "outer", "geometry": [{"lon": x, "lat": y} for x, y in _sq(0.002, 0.006, 0.002)]}]},
]


def test_courses_skip_disused_ranges_and_construction():
    p = golf.parse(ELEMENTS)
    courses = golf.courses(p, construction={"way/4"})
    assert [c["id"] for c in courses] == ["way/1"]
    assert [c["id"] for c in golf.construction(p, {"way/4"})] == ["way/4"]
    kinds = {k: len(v) for k, v in p["features"].items()}
    assert kinds == {"fairway": 1, "bunker": 1, "water_hazard": 1, "rough": 1}  # relation geometry assembled
    assert golf.water_hazards(p)[0].area > 0


def _rgb(h, s, v):
    return [round(c * 255) for c in colorsys.hsv_to_rgb(h / 360, s, v)]


def test_golf_band_greens_saturated_and_bleached_fairways():
    # Byrne fairway: aerial S ~0.61 (above DORMANT_BAND's 0.60); Saint
    # Martin's bleached fairway: V ~0.86, S ~0.21
    byrne, bleached, sand = _rgb(48, 0.62, 0.55), _rgb(55, 0.21, 0.86), _rgb(40, 0.25, 0.90)
    px = np.array([[byrne, bleached, sand]], np.uint8)
    assert not lawns.dormant_weight(px)[0, 0] and not lawns.dormant_weight(px)[0, 1]
    out = lawns.correct_golf(px, np.ones((1, 3), np.float32), fairway=np.array([[True, True, False]]))
    h, s, v = _hsv(out[0])
    assert 75 <= h[0] <= 90 and 75 <= h[1] <= 90, h
    assert s[1] >= 0.25, "bleached fairway reads as grass, not sand"
    v0 = _hsv(px[0])[2]
    assert np.allclose(v[:2], v0[:2], atol=0.08), "texture (brightness) kept"


def test_fairways_lighter_and_yellower_than_rough():
    grass = _rgb(50, 0.40, 0.55)
    px = np.array([[grass, grass]], np.uint8)
    out = lawns.correct_golf(px, np.ones((1, 2), np.float32), fairway=np.array([[True, False]]))
    h, _, v = _hsv(out[0])
    assert h[0] < h[1], "fairway hue is yellower (lower) than rough"
    assert v[0] >= v[1]


def test_zero_weight_changes_nothing():
    px = np.array([[_rgb(50, 0.4, 0.5)]], np.uint8)
    assert np.array_equal(lawns.correct_golf(px, np.zeros((1, 1), np.float32), np.ones((1, 1), bool)), px)



def test_ppr_golf_property_over_a_construction_course_is_construction():
    # Nov. 4: PPR's "Cobbs Creek Golf Course" property counts as a course
    # (PPR "Golf" names, for Walnut Lane), and 26% of it lies outside OSM's
    # construction outlines: the park meadow between Olde and Karakung. It
    # got the golf correction, turned pale green with straight edges against
    # the graded earth, and the model drew a lake there. A PPR golf property
    # mostly over reviewed construction courses is construction as a whole.
    from shapely.geometry import box

    olde, karakung = box(0, 0, 400, 300), box(400, 0, 700, 300)
    cobbs_ppr = box(0, 0, 700, 420)  # the courses plus the meadow north of them
    walnut_lane = box(2000, 0, 2400, 300)  # an active course elsewhere
    rec_center = box(450, 320, 520, 400)  # a separate park inside the meadow area
    out = golf.ppr_construction([cobbs_ppr, walnut_lane, rec_center], [olde, karakung])
    assert out == [0], "only the property mostly over construction courses"
    assert golf.ppr_construction([cobbs_ppr], []) == []
