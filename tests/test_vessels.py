"""Ships (Nov. 5, Stephen): traced vessel outlines from the 2024 aerial
(config/vessels.json), OSM piers, the water repaint's protection mask, and
vessel hulls built over water. Synthetic pixels and grids only."""

import numpy as np
from shapely.geometry import Polygon, box

from pixelphilly import vessels, waterpaint


WATER = (108, 101, 64)  # the Delaware in the 2024 aerial (south_lidar's color model)


def _scene():
    """A 400 x 300 px river with a gray ship (deck plus a darker hull edge),
    the ship's shadow, a pier, and ripples."""
    rng = np.random.default_rng(1)
    img = np.zeros((300, 400, 3), np.uint8)
    img[:] = WATER
    img = np.clip(img.astype(int) + rng.integers(-8, 9, img.shape), 0, 255).astype(np.uint8)
    img[100:140, 60:300] = (150, 150, 146)  # deck
    img[140:144, 60:300] = (55, 55, 58)  # dark hull side
    img[144:160, 70:310] = (45, 42, 28)  # shadow on the water
    img[200:230, 0:180] = (150, 100, 80)  # brick pier
    water = np.ones((300, 400), bool)
    pier = np.zeros((300, 400), bool)
    pier[198:232, 0:182] = True
    return img, water, pier


def test_trace_finds_the_hull_not_the_shadow_or_pier():
    img, water, pier = _scene()
    comps = vessels.trace(img, water, pier, mpp=0.25, min_m2=150)
    assert len(comps) == 1
    m = comps[0]
    assert m[100:140, 60:300].mean() > 0.97, "deck"
    assert m[150:160, 80:300].mean() < 0.1, "shadow on the water is not hull"
    assert not m[200:230].any(), "pier is excluded"
    assert not m[:90].any() and not m[170:].any(), "open water stays water"


def test_trace_drops_specks_and_open_water():
    img, water, pier = _scene()
    img[100:160] = WATER  # no ship
    img[20:24, 20:24] = (200, 200, 200)  # a buoy, 1 m²
    assert vessels.trace(img, water, pier, mpp=0.25, min_m2=150) == []


def test_protect_mask_keeps_hull_and_pier_and_repaints_water():
    # The repaint's color test calls the dark hull and the brick pier "water"
    # ([108,101,64] with tolerance 68); the protection mask must win
    img, water, pier = _scene()
    median, threshold = np.array(WATER, float), 68.0
    nhd = np.ones(img.shape[:2], bool)
    none = np.zeros(img.shape[:2], bool)
    unprotected = waterpaint.water_mask(img, nhd, none, median, threshold)
    assert unprotected[140:144, 80:280].mean() > 0.5 and unprotected[205:225, 10:170].mean() > 0.5
    protect = none.copy()
    protect[98:146, 58:302] = True
    protect |= pier
    w = waterpaint.water_mask(img, nhd, none | protect, median, threshold)
    assert not w[100:144, 60:300].any() and not w[200:230, 0:180].any()
    assert w[20:90, 20:380].mean() > 0.95 and w[250:290].mean() > 0.95, "open river still repaints"


def test_pier_polygons_from_osm_areas_and_lines():
    els = [
        {"type": "way", "id": 1, "tags": {"man_made": "pier"},
         "geometry": [{"lon": x, "lat": y} for x, y in [(0, 0), (0.001, 0), (0.001, 0.0002), (0, 0.0002), (0, 0)]]},
        {"type": "way", "id": 2, "tags": {"man_made": "pier", "width": "4"},
         "geometry": [{"lon": 0.002, "lat": 0}, {"lon": 0.003, "lat": 0}]},
        {"type": "way", "id": 3, "tags": {"building": "ship"},
         "geometry": [{"lon": 0.004, "lat": 0}, {"lon": 0.005, "lat": 0}]},
    ]
    polys = vessels.pier_polygons(els)
    assert len(polys) == 2
    area_m2 = polys[1].area * 111_320 ** 2
    assert 300 < area_m2 < 600, "a 111 m line buffered to its 4 m width"


def test_vessel_parts_whole_hull_at_water_level():
    # A same-berth ship: LiDAR deck at 12 m NAVD88 with a 25 m superstructure
    # and gaps (no returns) the old rules split on. The traced hull gives one
    # vessel, its base at the water level (not the 2.5 m pier ground)
    res = 0.5
    origin = (0.0, 100.0)  # x0, y_top
    struct = np.full((200, 200), np.nan, np.float32)
    struct[40:80, 20:180] = 12.0
    struct[50:70, 90:120] = 25.0
    struct[40:80, 60:64] = np.nan  # gap across the hull
    hull = box(10, 60, 90, 80)  # local m: x 10-90, y 60-80 -> rows 40-80, cols 20-180
    parts, measured = vessels.vessel_parts(hull, struct, origin, res, water_level=0.0, default_h=8.0)
    assert measured
    hs = sorted(round(p["h"]) for p in parts)
    assert hs[0] == 12 and hs[-1] == 25, hs
    covered = sum(Polygon(p[0], p[1:]).area for part in parts for p in part["polys"])
    assert covered > 0.9 * hull.area, "no gap in the hull (parts are inset 0.5 m)"


def test_vessel_parts_without_lidar_is_a_flat_hull_of_the_given_height():
    res = 0.5
    struct = np.full((100, 100), np.nan, np.float32)
    hull = box(5, 20, 45, 30)
    parts, measured = vessels.vessel_parts(hull, struct, (0.0, 50.0), res, water_level=0.0, default_h=9.0)
    assert not measured
    assert len(parts) == 1 and parts[0]["h"] == 9.0
    assert abs(Polygon(parts[0]["polys"][0][0]).area - hull.area) < 1e-6


def test_lidar_fragments_under_a_hull_give_way_to_it_but_cranes_stay():
    # A ship's LiDAR fragments (regions mostly inside the reviewed hull) are
    # replaced by the whole hull; a crane on the quay beside it and a barge
    # elsewhere keep their LiDAR parts
    def part(region, poly, h=10.0):
        return {"region": region, "h": h, "polys": [[list(poly.exterior.coords)]], "over_water": True}

    hull = box(0, 0, 100, 20)
    frags = [part(0, box(10, 2, 30, 18)), part(0, box(30, 5, 40, 15), 20.0), part(1, box(60, 4, 80, 16))]
    crane = part(2, box(95, 18, 120, 40), 40.0)  # overlaps the hull's corner a little
    barge = part(3, box(200, 0, 240, 10), 3.0)
    kept, dropped = vessels.drop_fragments([*frags, crane, barge], [hull])
    assert sorted({p["region"] for p in kept}) == [2, 3]
    assert dropped == 2
