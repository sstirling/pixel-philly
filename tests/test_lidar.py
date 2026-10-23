"""Stepped building parts from a LiDAR height grid (synthetic shapes)."""

import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box, shape

from pixelphilly.lidar import building_parts, tier_step

RES = 0.5
SIZE = 600  # grid cells: 300 m square, local meters from -150 to +150
ORIGIN = (-150.0, 150.0)  # west edge, north edge


def grid_coords():
    c = (np.arange(SIZE) + 0.5) * RES
    e = ORIGIN[0] + c
    n = ORIGIN[1] - c
    return np.meshgrid(e, n)  # E varies along columns, N along rows (north at row 0)


def parts_union(parts):
    from shapely.ops import unary_union

    return unary_union([Polygon(p[0], p[1:]) for part in parts for p in part["polys"]])


def test_tier_step_scales_with_height():
    assert tier_step(10) == 2.0
    assert tier_step(150) == pytest.approx(9.0)


def test_dome_becomes_nested_terraces():
    E, N = grid_coords()
    r = np.hypot(E, N)
    R = 20.0
    ndsm = np.where(r < R, 30 * np.sqrt(np.clip(1 - (r / R) ** 2, 0, 1)), 0.0)
    parts = building_parts(Point(0, 0).buffer(R), ndsm, ORIGIN, RES)
    heights = sorted({p["h"] for p in parts})
    assert len(heights) >= 4, heights
    assert max(heights) == pytest.approx(30, abs=2.5)
    # Higher terraces sit inside lower ones: the tallest part is near the center
    top = max(parts, key=lambda p: p["h"])
    assert Polygon(top["polys"][0][0]).distance(Point(0, 0)) < 5


def test_stadium_field_stays_open_and_stands_form_a_ring():
    E, N = grid_coords()
    r = np.hypot(E, N)
    ndsm = np.where(r < 40, 0.3, np.where(r < 95, np.interp(r, [45, 95], [2, 30]), 0.0))
    parts = building_parts(Point(0, 0).buffer(100), ndsm, ORIGIN, RES)
    u = parts_union(parts)
    assert not u.contains(Point(0, 0)), "the field must be open ground"
    assert u.contains(Point(70, 0)) and u.contains(Point(0, -70)), "the stands must be built"
    assert max(p["h"] for p in parts) == pytest.approx(30, abs=3)


def test_tower_on_a_base_becomes_a_tall_thin_part():
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 20) & (abs(N) < 20), 15.0, 0.0)
    ndsm = np.where((abs(E) < 4) & (abs(N) < 4), 150.0, ndsm)
    parts = building_parts(box(-20, -20, 20, 20), ndsm, ORIGIN, RES)
    tall = [p for p in parts if p["h"] > 140]
    assert tall, parts
    area = parts_union(tall).area
    assert 30 < area < 90, area  # about 8 x 8 m, less the 0.5 m inset
    assert any(abs(p["h"] - 15) < 2 for p in parts)


def test_isolated_spikes_do_not_become_parts():
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 30) & (abs(N) < 30), 12.0, 0.0)
    rng = np.random.default_rng(0)
    for _ in range(40):  # single-cell spikes, like antennas or stray returns
        i, j = rng.integers(250, 350, 2)
        ndsm[i, j] = 60.0
    parts = building_parts(box(-30, -30, 30, 30), ndsm, ORIGIN, RES)
    assert all(p["h"] < 20 for p in parts), sorted(p["h"] for p in parts)
    for p in parts:
        assert Polygon(p["polys"][0][0], p["polys"][0][1:]).area >= 6.0


def test_no_coverage_returns_none():
    ndsm = np.full((SIZE, SIZE), np.nan)
    assert building_parts(box(-10, -10, 10, 10), ndsm, ORIGIN, RES) is None


def _write_las(path, x, y, z, cls):
    import laspy

    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = [0.01, 0.01, 0.01]
    header.offsets = [float(np.min(x)), float(np.min(y)), 0.0]
    las = laspy.LasData(header)
    las.x, las.y, las.z = x, y, z
    las.classification = cls
    las.write(path)


def test_dsm_from_las_grids_max_and_ground_and_ignores_outside_points(tmp_path):
    from pyproj import Transformer

    from pixelphilly.lidar import LAS_CRS, US_FT_TO_M, dsm_from_las
    from pixelphilly.projection import LocalFrame

    bbox = [-75.1650, 39.9515, -75.1620, 39.9530]
    frame = LocalFrame(bbox)
    to_sp = Transformer.from_crs("EPSG:4326", LAS_CRS, always_xy=True)
    # Two points in the same cell at local (0, 0): roof 100 ft and 50 ft;
    # one ground point at local (5, 0); one point far outside the area
    lon, lat = frame.to_wgs84([0.1, 0.2, 5.1, 2000.0], [0.1, 0.2, 0.1, 2000.0])
    x, y = to_sp.transform(lon, lat)
    z = np.array([100.0, 50.0, 30.0, 999.0])
    cls = np.array([1, 1, 2, 1], dtype=np.uint8)
    inside = tmp_path / "inside.las"
    _write_las(inside, np.asarray(x), np.asarray(y), z, cls)
    # A tile whose points all fall outside the area must not break gridding
    lon2, lat2 = frame.to_wgs84([3000.0, 3001.0], [3000.0, 3001.0])
    x2, y2 = to_sp.transform(lon2, lat2)
    outside = tmp_path / "outside.las"
    _write_las(outside, np.asarray(x2), np.asarray(y2), np.array([10.0, 20.0]), np.array([1, 2], dtype=np.uint8))

    dsm, ground, origin = dsm_from_las([outside, inside], frame, (-10, -10, 10, 10), 0.5)
    col, row = int((0.1 - origin[0]) / 0.5), int((origin[1] - 0.1) / 0.5)
    assert dsm[row, col] == pytest.approx(100 * US_FT_TO_M, abs=0.02)
    gcol = int((5.1 - origin[0]) / 0.5)
    assert ground[row, gcol] == pytest.approx(30 * US_FT_TO_M, abs=0.02)
    assert np.nanmax(dsm) < 999 * US_FT_TO_M  # the far point was ignored


def test_noise_above_the_city_ceiling_is_dropped_and_filled():
    # Real case: ~1,200 class-1 returns 80-110 m above the Ritz-Carlton
    # residences roof, all from one flight line. The footprint's L&I
    # max_hgt is the ceiling; cells above it are noise, refilled from the roof
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 15) & (abs(N) < 15), 150.0, 0.0)
    ndsm = np.where((abs(E - 3) < 3) & (abs(N - 3) < 3), 260.0, ndsm)  # 36 m² blob
    parts = building_parts(box(-15, -15, 15, 15), ndsm, ORIGIN, RES, ceiling=160.0)
    assert max(p["h"] for p in parts) < 163, sorted(p["h"] for p in parts)
    u = parts_union(parts)
    assert u.contains(Point(3, 3)), "noise cells are refilled, not left as a hole"
    tall = [p for p in parts if p["h"] > 140]
    assert parts_union(tall).area > 0.9 * 29 * 29


def test_ceiling_keeps_real_shapes_below_it():
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 20) & (abs(N) < 20), 15.0, 0.0)
    ndsm = np.where((abs(E) < 4) & (abs(N) < 4), 150.0, ndsm)
    with_ceiling = building_parts(box(-20, -20, 20, 20), ndsm, ORIGIN, RES, ceiling=152.0)
    assert with_ceiling == building_parts(box(-20, -20, 20, 20), ndsm, ORIGIN, RES)


def test_small_spike_far_above_its_roof_is_dropped_even_under_the_ceiling():
    # Real case: City Hall's ceiling is 170 m (the tower), so a 19 m² cluster
    # of stray returns at 150 m on the ~50 m east wing passed the ceiling and
    # rendered as a needle spire. A real tower in the same footprint stays
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 60) & (abs(N) < 60), 50.0, 0.0)
    ndsm = np.where((abs(E + 30) < 10) & (abs(N + 30) < 10), 150.0, ndsm)  # real tower, 400 m²
    ndsm = np.where((abs(E - 35) < 2.25) & (abs(N - 30) < 2.25), 150.0, ndsm)  # spike, ~20 m²
    parts = building_parts(box(-60, -60, 60, 60), ndsm, ORIGIN, RES, ceiling=170.0)
    tall = parts_union([p for p in parts if p["h"] > 100])
    assert tall.contains(Point(-30, -30)), "the real tower is kept"
    assert not tall.intersects(Point(35, 30).buffer(3)), "the spike is flattened into the roof"
    assert parts_union(parts).contains(Point(35, 30)), "and filled, not left as a hole"


def test_tapered_steeple_is_kept():
    # Real steeples taper: Independence Hall's runs continuously from its
    # tower body (~25-30 m) to ~42 m. Each step up is small, so a steeple
    # isn't a spike even with no City record
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 20) & (abs(N) < 8), 15.0, 0.0)  # nave
    ndsm = np.where((abs(E - 12) < 4) & (abs(N) < 4), 30.0, ndsm)  # tower, 64 m²
    ndsm = np.where((abs(E - 12) < 2) & (abs(N) < 2), 42.0, ndsm)  # belfry, 16 m²
    ndsm = np.where((abs(E - 12) < 1) & (abs(N) < 1), 52.0, ndsm)  # spire, 4 m²
    parts = building_parts(box(-20, -8, 20, 8), ndsm, ORIGIN, RES)
    assert any(p["h"] > 40 for p in parts), sorted(p["h"] for p in parts)
    assert any(25 < p["h"] < 35 for p in parts)


def test_spike_matching_an_inflated_city_record_is_still_dropped():
    # Real case: 226-30 N 2nd St, an 18 m rowhouse block with max_hgt 203 ft
    # (62 m). The City's max_hgt is its highest LiDAR return, so the same
    # stray cluster set it; matching the record proves nothing. The 2024
    # aerial shows no tower and no shadow
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 15) & (abs(N) < 10), 18.0, 0.0)
    ndsm = np.where((abs(E - 5) < 2) & (abs(N) < 2), 62.0, ndsm)  # 16 m²
    parts = building_parts(box(-15, -10, 15, 10), ndsm, ORIGIN, RES, ceiling=62.0)
    assert max(p["h"] for p in parts) < 25, sorted(p["h"] for p in parts)


def test_cityhall_downtown_grid_has_no_stray_spire():
    # Real data: City Hall (footprint 489522) cut from the downtown_lidar grid.
    # The atlas grid flattened both wing clusters, but on the downtown grid's
    # cell alignment the west one (145.7 m, 8.9 m², ~60 m from the tower)
    # survived. Only the tower may rise above 100 m; William Penn stays
    from pathlib import Path

    from shapely import wkt

    z = np.load(Path(__file__).parent / "fixtures" / "cityhall_downtown_grid.npz")
    fp = wkt.loads(str(z["footprint_wkt"]))
    parts = building_parts(fp, z["dsm"], tuple(z["origin"]), RES, base=float(z["base"]), ceiling=float(z["ceiling"]))
    top = max(parts, key=lambda p: p["h"])
    assert top["h"] == pytest.approx(167, abs=3)
    tower = Polygon(top["polys"][0][0]).centroid
    far_tall = [(p["h"], Polygon(p["polys"][0][0]).centroid.distance(tower)) for p in parts
                if p["h"] > 100 and Polygon(p["polys"][0][0]).centroid.distance(tower) > 25]
    assert not far_tall, far_tall


def test_separate_regions_in_one_tier_keep_their_own_heights():
    # Two blocks at 140 m and 148 m fall in the same tier (step 12 m under a
    # 200 m tower); each part must carry its own measured height, not the
    # tier-wide median (why both City Hall spikes read exactly 150.35 m)
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 40) & (abs(N) < 15), 20.0, 0.0)
    ndsm = np.where((abs(E + 25) < 5) & (abs(N) < 5), 140.0, ndsm)
    ndsm = np.where((abs(E) < 5) & (abs(N) < 5), 148.0, ndsm)
    ndsm = np.where((abs(E - 25) < 5) & (abs(N) < 5), 200.0, ndsm)
    parts = building_parts(box(-40, -15, 40, 15), ndsm, ORIGIN, RES)

    def h_at(x):
        return max(p["h"] for p in parts if any(Polygon(r[0], r[1:]).contains(Point(x, 0)) for r in p["polys"]))

    assert h_at(-25) == pytest.approx(140, abs=1)
    assert h_at(0) == pytest.approx(148, abs=1)


def test_statue_confirmed_by_city_record_is_kept():
    # William Penn: ~2 x 2 m at 167 m on City Hall's ~150 m tower top. The
    # LiDAR has it, but the median filter and 6 m² speck merge erased it.
    # The City record (170 m) confirms it, so it stays
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 10) & (abs(N) < 10), 150.0, 0.0)
    ndsm = np.where((abs(E) < 1) & (abs(N) < 1), 167.0, ndsm)
    parts = building_parts(box(-10, -10, 10, 10), ndsm, ORIGIN, RES, ceiling=170.0)
    assert max(p["h"] for p in parts) >= 165, sorted(p["h"] for p in parts)


def test_small_tall_region_without_a_record_still_merges():
    # Without a City record nothing confirms the cluster, so stray points can't
    # become parts on their own
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 10) & (abs(N) < 10), 150.0, 0.0)
    ndsm = np.where((abs(E) < 1) & (abs(N) < 1), 167.0, ndsm)
    parts = building_parts(box(-10, -10, 10, 10), ndsm, ORIGIN, RES)
    assert max(p["h"] for p in parts) < 155


def test_spike_is_dropped_when_the_building_has_no_city_record():
    # Real case: footprint 545892 next to the Cathedral Basilica has no City
    # height; two 7 m² clusters at 160-180 m on its 74 m roof drew as spires.
    # With no record, nothing confirms a spire, so the spike rule still applies
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 20) & (abs(N) < 20), 74.0, 0.0)
    ndsm = np.where((abs(E - 8) < 1.5) & (abs(N - 8) < 1.5), 179.0, ndsm)  # 9 m²
    ndsm = np.where((abs(E + 8) < 1.5) & (abs(N + 8) < 1.5), 160.0, ndsm)
    parts = building_parts(box(-20, -20, 20, 20), ndsm, ORIGIN, RES)
    assert max(p["h"] for p in parts) < 80, sorted(p["h"] for p in parts)
    u = parts_union(parts)
    assert u.contains(Point(8, 8)) and u.contains(Point(-8, -8)), "filled, not holes"


def test_region_matching_the_typical_city_height_is_kept():
    # Real case: 1224 Chestnut St, typical height (approx_hgt) 134 ft / 41 m;
    # a 25 m² part at 41.5 m stands over 17 m surroundings. approx_hgt is the
    # City's typical height, which stray returns don't move (unlike max_hgt,
    # the highest return), so a region at that height is the building itself.
    # Same for the Linc's canopy pieces (typical 55 m) on near-ground cells
    E, N = grid_coords()
    ndsm = np.where((abs(E) < 15) & (abs(N) < 10), 17.0, 0.0)
    ndsm = np.where((abs(E - 5) < 2.5) & (abs(N) < 2.5), 41.5, ndsm)  # 25 m²
    parts = building_parts(box(-15, -10, 15, 10), ndsm, ORIGIN, RES, ceiling=42.4, typical=40.8)
    assert any(p["h"] > 38 for p in parts), sorted(p["h"] for p in parts)
    # The same region over a building whose typical height is the low roof is a spike
    parts = building_parts(box(-15, -10, 15, 10), ndsm, ORIGIN, RES, ceiling=42.4, typical=17.0)
    assert max(p["h"] for p in parts) < 25


def test_franklin_field_upper_deck_keeps_its_cascade_and_open_field():
    # Real data: Franklin Field (footprint 106422), ~1.2 ha. Two bugs:
    # 1. The base came from ground in a ring outside the footprint, which
    #    dips into the rail cut to the east: base 7.0 m vs. the field at
    #    ~11.7 m, so the field drew as a 4.7 m slab and every part sat 4.7 m
    #    high. A stadium has ground returns of its own (the field), and they
    #    give the true base.
    # 2. LiDAR shows the upper deck rising in rows from ~15 m to ~25 m above
    #    the field, but the 60-part cap coarsened the tiers until those rows
    #    vanished (parts jumped 10.9 -> 19.6 m) and the stand drew as a
    #    flat-roofed building. The cap stops small buildings fragmenting; it
    #    shouldn't flatten a stadium's seating.
    from pathlib import Path

    from shapely import wkt

    from pixelphilly.lidar import footprint_base

    z = np.load(Path(__file__).parent / "fixtures" / "franklinfield_grid.npz")
    fp = wkt.loads(str(z["footprint_wkt"]))
    origin = tuple(z["origin"])
    base = footprint_base(fp, z["ground"], origin, RES)
    parts = building_parts(fp, z["dsm"], origin, RES, base=base,
                           ceiling=float(z["ceiling"]), typical=float(z["typical"]))
    assert not parts_union(parts).contains(Point(*z["field_center"])), "the field is open ground"
    deck = sorted({round(p["h"]) for p in parts if 13 <= p["h"] <= 27})
    assert len(deck) >= 5, deck
    assert any(13 <= p["h"] <= 17 for p in parts), "the upper deck's front rows"
