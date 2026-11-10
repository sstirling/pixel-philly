"""Bridges (Nov. 5, Stephen: "water is bleeding onto the roads"). Bridge
decks over the river are flat aerial texture in the render, and the drawing
puts the deck and its truss a few pixels off; the river color test then
repaints deck pixels blue. Inside a bridge band the repaint now only takes
pixels the raw drawing drew as water. Synthetic pixels."""

import numpy as np
from shapely.geometry import LineString

from pixelphilly import bridges, waterpaint

RIVER_RENDER = (108, 101, 64)
DRAWN_RIVER = (120, 112, 80)  # the model's brownish water
DECK = (150, 150, 146)
ASPHALT_RENDER = (95, 92, 80)  # dark asphalt: inside the river tolerance


def _scene():
    rng = np.random.default_rng(3)
    H, W = 200, 300
    render = np.zeros((H, W, 3), np.uint8)
    render[:] = RIVER_RENDER
    render[90:110] = ASPHALT_RENDER  # the deck in the render, at y = 0
    drawing = np.zeros((H, W, 3), np.uint8)
    drawing[:] = DRAWN_RIVER
    drawing[96:118] = DECK  # drawn deck (and truss) sits lower on screen
    drawing[118:122] = (60, 60, 64)  # dark truss edge
    # ripple dashes in the drawn river, inside the band too
    for y, x in [(80, 40), (125, 200), (130, 60)]:
        drawing[y:y + 2, x:x + 6] = (190, 185, 160)
    render = np.clip(render.astype(int) + rng.integers(-5, 6, render.shape), 0, 255).astype(np.uint8)
    drawing = np.clip(drawing.astype(int) + rng.integers(-5, 6, drawing.shape), 0, 255).astype(np.uint8)
    return render, drawing


def test_bleed_repro_without_the_band_the_deck_is_repainted():
    render, drawing = _scene()
    nhd = np.ones(render.shape[:2], bool)
    none = np.zeros(render.shape[:2], bool)
    water = waterpaint.water_mask(render, nhd, none, np.array(RIVER_RENDER, float), 68.0)
    assert water[100:118, 20:280].mean() > 0.8, "the bug: deck pixels count as river"


def test_band_keeps_the_drawn_deck_and_repaints_the_river_around_it():
    render, drawing = _scene()
    nhd = np.ones(render.shape[:2], bool)
    none = np.zeros(render.shape[:2], bool)
    water = waterpaint.water_mask(render, nhd, none, np.array(RIVER_RENDER, float), 68.0)
    band = np.zeros(render.shape[:2], bool)
    band[70:150] = True  # the deck's band, generous
    out = bridges.refine(water, drawing, band)
    assert not out[97:122, 20:280].any(), "drawn deck and truss stay"
    assert out[72:94, 20:280].mean() > 0.97 and out[124:148, 20:280].mean() > 0.97, "drawn river in the band repaints"
    assert out[80:82, 40:46].all() and out[130:132, 60:66].all(), "ripple dashes in the band go with the river"
    assert (out[:70] == water[:70]).all() and (out[150:] == water[150:]).all(), "outside the band nothing changes"


def test_band_geometry_from_lines_over_water():
    from shapely.geometry import box

    water = box(0, 0, 100, 100)
    road = LineString([(-50, 50), (150, 50)])  # crosses the river
    shore = LineString([(-50, -20), (150, -20)])  # never over water
    g = bridges.deck_geometry([(road, 10.0), (shore, 10.0)], water, min_len_m=8.0)
    assert g.covers(box(0, 46, 100, 54)) and not g.intersects(box(0, -30, 100, -10))
    assert g.area <= (100 + 2 * 6) * (2 * 10) + 1e-6, "tight: the over-water stretch plus the 6 m margin, half width 10 m"


def test_osm_bridge_widths_from_tags():
    els = [
        {"type": "way", "id": 1, "tags": {"highway": "motorway", "bridge": "yes", "lanes": "4"},
         "geometry": [{"lon": 0, "lat": 0}, {"lon": 0.001, "lat": 0}]},
        {"type": "way", "id": 2, "tags": {"railway": "rail", "bridge": "viaduct"},
         "geometry": [{"lon": 0, "lat": 0}, {"lon": 0.001, "lat": 0}]},
        {"type": "way", "id": 3, "tags": {"highway": "footway", "bridge": "yes", "width": "5"},
         "geometry": [{"lon": 0, "lat": 0}, {"lon": 0.001, "lat": 0}]},
        {"type": "way", "id": 4, "tags": {"highway": "residential", "bridge": "no"},
         "geometry": [{"lon": 0, "lat": 0}, {"lon": 0.001, "lat": 0}]},
    ]
    got = bridges.osm_bridge_lines(els)
    assert [round(h, 1) for _, h in got] == [9.2, 6.0, 2.5]  # 4 lanes x 3.6 m + 4 m shoulders


def test_deck_mask_keeps_dark_deck_pixels_that_look_like_drawn_river():
    render, drawing = _scene()
    drawing[100:106] = DRAWN_RIVER  # dark asphalt drawn in the river's own color
    nhd = np.ones(render.shape[:2], bool)
    none = np.zeros(render.shape[:2], bool)
    water = waterpaint.water_mask(render, nhd, none, np.array(RIVER_RENDER, float), 68.0)
    band = np.zeros(render.shape[:2], bool)
    band[70:150] = True
    deck = np.zeros(render.shape[:2], bool)
    deck[92:108] = True  # the render's deck, narrowed
    out = bridges.refine(water, drawing, band, deck)
    assert not out[92:108].any()
    assert out[72:90, 20:280].mean() > 0.97


def test_refine_handles_a_river_drawn_in_fewer_colors_than_the_palette():
    # upper_northeast crashed: quantize returned 5 colors for 8 requested
    render, drawing = _scene()
    drawing[:] = DRAWN_RIVER  # flat, one color: no noise
    drawing[96:118] = DECK
    nhd = np.ones(render.shape[:2], bool)
    none = np.zeros(render.shape[:2], bool)
    water = waterpaint.water_mask(render, nhd, none, np.array(RIVER_RENDER, float), 68.0)
    band = np.zeros(render.shape[:2], bool)
    band[70:150] = True
    out = bridges.refine(water, drawing, band)
    assert not out[97:118, 20:280].any() and out[72:94, 20:280].mean() > 0.97


# Nov. 8 review: where every bit of river in a frame's view lies inside a
# bridge band (the Schuylkill at Walnut St; a road along the shore), refine()
# had no drawn river to learn colors from and left the whole band unpainted:
# a block of raw teal with straight frame edges. Colors from nearby frames
# (SampleBank) fill in.

TEAL = (108, 139, 135)  # the Schuylkill as drawn near Center City
BROWN = (123, 112, 81)  # the Delaware as drawn


def _all_band_scene():
    render, drawing = _scene()
    drawing[:96] = TEAL
    drawing[122:] = TEAL
    nhd = np.ones(render.shape[:2], bool)
    none = np.zeros(render.shape[:2], bool)
    water = waterpaint.water_mask(render, nhd, none, np.array(RIVER_RENDER, float), 68.0)
    band = np.ones(render.shape[:2], bool)  # the band covers the whole view
    return water, drawing, band


def test_band_covering_all_water_repaints_with_a_nearby_sample():
    water, drawing, band = _all_band_scene()
    assert not bridges.refine(water, drawing, band).any(), "the bug: no ring, nothing repainted"
    sample = np.tile(np.array(TEAL, np.uint8), (500, 1))
    out = bridges.refine(water, drawing, band, sample=sample)
    assert out[10:90, 20:280].mean() > 0.97 and out[126:190, 20:280].mean() > 0.97, "drawn river repaints"
    assert not out[97:122, 20:280].any(), "drawn deck and truss stay"


def test_ring_sample_is_none_without_drawn_river_outside_the_band():
    water, drawing, band = _all_band_scene()
    assert bridges.ring_sample(water, drawing, band) is None
    band[:] = False
    band[90:125] = True
    s = bridges.ring_sample(water, drawing, band)
    assert s is not None and s.shape[1] == 3


def test_sample_bank_takes_colors_from_the_nearest_frames():
    bank = bridges.SampleBank()
    bank.add((0, 0), np.tile(np.array(TEAL, np.uint8), (300, 1)))
    bank.add((6, 6), np.tile(np.array(BROWN, np.uint8), (300, 1)))
    near = bank.near((1, 0))
    assert near is not None and (near == TEAL).all(), "only the closest frames, not the whole area"
    assert bank.near((20, 20)) is None, "nothing within reach: keep the drawing"


# Nov. 9, Stephen: the Ben Franklin and Walt Whitman bridges "look awful";
# the Walt Whitman "has buildings on the roadway." Two causes in the render:
# (1) the 2022 LiDAR saw the elevated decks, and the scene extruded them as
# blocks (structure s1745 on the WWB main span at 47-59 m; footprint
# 326703's parts stepping up to 40 m under the WWB approach); (2) the 2024
# aerial's long bridge shadows on the river, which the model draws as a gray
# slab with a ghost bridge in it.

def _way(i, coords, **tags):
    return {"type": "way", "id": i, "tags": {"bridge": "yes", **tags},
            "geometry": [{"lon": x, "lat": y} for x, y in coords]}


def test_deck_corridors_cover_motorway_bridges_only():
    from shapely.geometry import Point

    els = [
        _way(1, [(0, 0), (100, 0)], highway="motorway", lanes="3"),
        _way(2, [(0, 200), (100, 200)], highway="residential"),  # a street bridge: not a high deck
        _way(3, [(0, 400), (100, 400)], railway="rail"),
        {"type": "way", "id": 4, "tags": {"highway": "motorway", "bridge": "no"},
         "geometry": [{"lon": 0, "lat": 600}, {"lon": 100, "lat": 600}]},
    ]
    corr = bridges.deck_corridors(els, lambda lon, lat: (np.asarray(lon, float), np.asarray(lat, float)))
    from shapely.ops import unary_union

    u = unary_union(corr)
    assert u.contains(Point(50, 0)) and u.contains(Point(50, 7.4 + bridges.DECK_PAD_M - 0.5))
    assert not u.contains(Point(50, 7.4 + bridges.DECK_PAD_M + 0.5)), "OSM half width plus the pad, no more"
    assert not u.intersects(Point(50, 200).buffer(1)) and not u.intersects(Point(50, 400).buffer(1))
    assert not u.intersects(Point(50, 600).buffer(1))


def _part(pid, x0, y0, x1, y1, h):
    return {"id": pid, "h": h, "polys": [[[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]]}


def test_footprint_parts_on_a_deck_are_dropped_and_the_rest_of_the_footprint_stays():
    from shapely.geometry import box

    corr = [box(0, -15, 300, 15)]  # a deck corridor
    blds = [
        _part("326703-1407", 100, -5, 110, 5, 39.7),  # LiDAR saw the deck above the footprint
        _part("326703-12", 100, -60, 140, -20, 6.0),  # the same terminal's shed, off the deck
        _part("326703-3", 200, -5, 210, 5, 4.0),  # a low part under the deck: a real roof edge is possible
        _part("88-0", 120, 10, 130, 40, 27.0),  # a tall building only touching the corridor
        _part("4711", 50, -5, 60, 5, 20.0),  # single-height footprint (no LiDAR parts): not ours to judge
        {**_part("s9-0", 150, -5, 160, 5, 45.0), "structure": True},  # structures go through the exclude mask
    ]
    kept, dropped = bridges.drop_deck_parts(blds, corr)
    assert [b["id"] for b in dropped] == ["326703-1407"]
    assert {b["id"] for b in kept} == {"326703-12", "326703-3", "88-0", "4711", "s9-0"}


def _river_scene():
    rng = np.random.default_rng(9)
    H, W = 240, 320
    rgb = np.zeros((H, W, 3), np.int16)
    rgb[:] = RIVER_RENDER
    rgb += rng.integers(-8, 9, rgb.shape).astype(np.int16)  # ripples
    water = np.ones((H, W), bool)
    water[:, :40] = False  # the shore
    rgb[:, :40] = (150, 140, 120)
    rgb[40:70, :40] = (35, 38, 45)  # a dark roof on land, inside the search zone
    rgb[100:130, 40:] = (150, 150, 146)  # the deck (inside its corridor)
    rgb[130:180, 40:] = (32, 36, 46)  # the deck's shadow on the river
    rgb[200:220, 150:230] = (30, 30, 34)  # a dark hull (a reviewed vessel)
    near = np.ones((H, W), bool)
    keep = np.zeros((H, W), bool)
    keep[96:134] = True  # the corridor: the deck itself is never touched
    protect = np.zeros((H, W), bool)
    protect[198:222, 148:232] = True
    return np.clip(rgb, 0, 255).astype(np.uint8), water, near, keep, protect


def test_bridge_shadow_on_the_river_is_filled_with_river():
    rgb, water, near, keep, protect = _river_scene()
    out, mask = bridges.clear_water_shadows(rgb, water, near & ~keep, protect)
    shadow = out[136:176, 60:300].astype(float)
    river = np.array(RIVER_RENDER, float)
    assert np.abs(shadow.mean(axis=(0, 1)) - river).max() < 12, "the shadow now reads as river"
    assert mask[134:178, 45:315].mean() > 0.97


def test_shadow_fill_leaves_land_the_deck_and_vessels_alone():
    rgb, water, near, keep, protect = _river_scene()
    out, mask = bridges.clear_water_shadows(rgb, water, near & ~keep, protect)
    assert (out[:, :40] == rgb[:, :40]).all(), "land (a dark roof) untouched"
    assert (out[96:134] == rgb[96:134]).all(), "the deck untouched"
    assert (out[198:222, 148:232] == rgb[198:222, 148:232]).all(), "the vessel untouched"
    assert not mask[:90, 45:].any(), "plain river with ripples isn't a shadow"


def test_shadow_edges_and_hanger_lines_connected_to_the_shadow_are_filled_too():
    # Real shadows have soft edges and thin, mid-dark hanger and cable lines
    # running off the slab; filling only the near-black core left their
    # outlines on the river (the WWB tower's ghost)
    rgb, water, near, keep, protect = _river_scene()
    rgb[180:183, 40:] = (70, 68, 55)  # the slab's soft edge
    rgb[183:240, 100:102] = (70, 68, 55)  # a hanger's shadow, joined to the slab...
    rgb[30:33, 60:120] = (70, 68, 55)  # ...and a mid-dark mark on its own (a wake, a ripple)
    out, mask = bridges.clear_water_shadows(rgb, water, near & ~keep, protect)
    assert mask[180:183, 45:315].mean() > 0.97, "the soft edge goes with the shadow"
    assert mask[183:236, 100:102].all(), "the hanger line connected to the shadow goes"
    assert not mask[30:33, 60:120].any(), "a mid-dark mark not touching a shadow stays"


def test_hanger_lattice_beside_a_shadow_is_filled_as_one_region_with_no_lines_left():
    # Nov. 9 render (output/review/bridges/nj/render_v2/bfb_mid.jpg): the BFB
    # tower and its hangers stayed on the river as faint lines. The hanger
    # shadows are only slightly darker than the river (~0.92), sit ~40 px
    # apart, and the ripple detail added back inside the fill engraved each
    # lit gap between dark lines. A lattice joined to the slab goes whole.
    rgb, water, near, keep, protect = _river_scene()
    lattice = rgb[180:236, 40:].astype(np.int16)
    for x in range(10, lattice.shape[1], 40):
        lattice[:, x:x + 3] = (np.array(RIVER_RENDER) * 0.92).astype(np.int16)  # faint hanger shadows
    rgb[180:236, 40:] = np.clip(lattice, 0, 255).astype(np.uint8)
    rgb[140:170, 100:300:40] = RIVER_RENDER  # lit gaps between cables inside the slab
    out, mask = bridges.clear_water_shadows(rgb, water, near & ~keep, protect)
    assert mask[182:196, 60:300].mean() > 0.97, "the lattice next to the slab is filled, gaps and all"
    luma = out[136:194, 60:300].astype(float) @ np.array([0.299, 0.587, 0.114])
    cols = luma.mean(axis=0)
    assert cols.max() - cols.min() < 6, "no hanger or gap lines left across the filled shadow"


def _tower_osm(way_id, corners):
    return {"type": "way", "id": way_id, "tags": {"man_made": "tower", "height": "117"},
            "geometry": [{"lon": x, "lat": y} for x, y in corners + corners[:1]]}


def test_tower_legs_are_two_square_legs_at_the_strip_ends_with_fixed_height_and_color():
    # Nov. 9: with the decks' LiDAR shapes gone, the model drew the Ben
    # Franklin with one tower and the Walt Whitman with none. Each OSM tower
    # outline is a thin strip across the deck (31 x 5 m); extruded whole it
    # would be a 116 m wall the model draws as a building, so it becomes two
    # square legs as wide as the strip, one at each end
    osm = [_tower_osm(7, [(0.0, 0.0), (31.0, 0.0), (31.0, 5.0), (0.0, 5.0)])]
    entries = [{"id": "bfb_pa", "osm_way": 7, "height_m": 116.4, "color": [86, 120, 156]}]
    legs = bridges.tower_legs(osm, entries, lambda lon, lat: (lon, lat))  # identity: lon/lat already meters
    assert sorted(b["id"] for b in legs) == ["tower-bfb_pa-a", "tower-bfb_pa-b"]
    from shapely.geometry import Polygon
    for b in legs:
        assert b["h"] == 116.4
        assert b["fixed_color"] == [86, 120, 156]
        assert "facade" not in b, "plain steel walls, no windows"
        g = Polygon(b["polys"][0][0], b["polys"][0][1:])
        assert abs(g.area - 25.0) < 0.5, "a 5 x 5 m leg"
    xs = sorted(Polygon(b["polys"][0][0]).centroid.x for b in legs)
    assert abs(xs[0] - 2.5) < 0.1 and abs(xs[1] - 28.5) < 0.1, "one leg at each end of the strip"


def test_tower_legs_fail_loudly_when_the_osm_outline_is_missing():
    import pytest

    entries = [{"id": "bfb_pa", "osm_way": 7, "height_m": 116.4, "color": [86, 120, 156]}]
    with pytest.raises(KeyError):
        bridges.tower_legs([], entries, lambda lon, lat: (lon, lat))


def test_tower_legs_grow_to_min_leg_m_centered_on_a_thin_strip():
    # The Walt Whitman's OSM strips are 3.3 m wide; legs that thin at 115 m
    # draw as needles. min_leg_m (an estimate) widens each leg about the
    # strip's center line
    osm = [_tower_osm(8, [(0.0, 0.0), (35.0, 0.0), (35.0, 3.0), (0.0, 3.0)])]
    entries = [{"id": "wwb_pa", "osm_way": 8, "height_m": 115.2, "color": [1, 2, 3], "min_leg_m": 5.0}]
    from shapely.geometry import Polygon
    legs = bridges.tower_legs(osm, entries, lambda lon, lat: (lon, lat))
    for b in legs:
        g = Polygon(b["polys"][0][0])
        assert abs(g.area - 25.0) < 0.5, "a 5 x 5 m leg"
        assert abs(g.centroid.y - 1.5) < 0.05, "centered on the strip"
    xs = sorted(Polygon(b["polys"][0][0]).centroid.x for b in legs)
    assert abs(xs[0] - 2.5) < 0.1 and abs(xs[1] - 32.5) < 0.1


# --- Suspension structure (Nov. 9): deck, cables, hangers, truss, crossbeams ---
# Synthetic bridge along +x in local meters (identity to_local): tower A at
# x = 0, tower B at x = 500, each an OSM strip 5 m along the bridge and 30 m
# across it, so tower_legs puts the leg centers at y = +/-12.5. Side spans of
# 200 m put the anchorages at x = -200 and x = 700.

def _v(x):
    return {"value": x, "unit": "m", "source": "https://example.org/test"}


def _bridge_entry(**over):
    dims = {"side_span_m": _v(200.0), "clearance_m": _v(40.0), "cable_sag_m": _v(50.0),
            "cable_radius_m": _v(0.75), "cable_anchor_above_deck_m": _v(0.0),
            "hanger_spacing_main_m": _v(10.0), "hanger_spacing_side_m": _v(10.0), "hanger_radius_m": _v(0.3),
            "deck_width_m": _v(30.0), "roadway_width_m": _v(24.0), "lanes": _v(7),
            "deck_thickness_m": _v(5.0), "vertical_curve_end_grade": _v(0.05),
            "lane_line_width_m": _v(0.4), "lane_line_height_m": _v(0.1), "dash_m": _v(3.05), "gap_m": _v(9.14),
            "crossbeams_m": _v([[60.0, 62.0], [95.0, 99.0]]), "x_bracing": _v(True), "strut_thickness_m": _v(3.0),
            "brace_radius_m": _v(0.6),
            "color": _v([1, 2, 3]), "deck_rgb": _v([74, 74, 78]), "lane_rgb": _v([230, 230, 225])}
    for k, val in over.items():
        if val is None:
            dims.pop(k, None)
        else:
            dims[k] = _v(val)
    return {"id": "test", "osm_deck_ways": [99], "tower_entries": ["t_a", "t_b"], "dims": dims}


def _bridge_osm():
    strip = lambda x: [(x - 2.5, -15.0), (x + 2.5, -15.0), (x + 2.5, 15.0), (x - 2.5, 15.0)]
    deck = {"type": "way", "id": 99, "tags": {"highway": "motorway", "bridge": "yes", "lanes": "3"},
            "geometry": [{"lon": -300.0, "lat": 0.0}, {"lon": 800.0, "lat": 0.0}]}
    return [_tower_osm(1, strip(0.0)), _tower_osm(2, strip(500.0)), deck]


_TOWERS = [{"id": "t_a", "osm_way": 1, "height_m": 100.0, "color": [1, 2, 3]},
           {"id": "t_b", "osm_way": 2, "height_m": 100.0, "color": [1, 2, 3]}]
_MHW = 1.0


def _lidar(cut_x=300.0):
    """dsm (NAVD88) of a deck rising 0.01 m/m from 30 m above MHW at x = 0,
    with no returns from cut_x on, like the Walt Whitman's NJ end outside
    the City's coverage."""
    res, west, north = 0.5, -350.0, 50.0
    cols, rows = 2400, 200
    x = west + (np.arange(cols) + 0.5) * res
    row = np.where(x < cut_x, _MHW + 30.0 + 0.01 * x, np.nan).astype(np.float32)
    return {"dsm": np.tile(row, (rows, 1)), "origin": (west, north), "res": res}


def _structure(entry=None, water=None, lidar=None):
    from shapely.geometry import box

    water = box(-100.0, -1000.0, 600.0, 1000.0) if water is None else water
    return bridges.suspension_structure(entry or _bridge_entry(), _bridge_osm(), _TOWERS, lambda lon, lat: (lon, lat),
                                        water=water, lidar=lidar, mhw_m=_MHW)


def _decks(out):
    from shapely.geometry import Polygon

    return sorted(((Polygon(b["polys"][0][0]).centroid.x, b) for b in out["buildings"] if "-deck-" in b["id"]),
                  key=lambda p: p[0])


def _deck_at(out, x):
    return min(_decks(out), key=lambda p: abs(p[0] - x))


def test_deck_profile_follows_the_lidar_and_falls_back_to_the_vertical_curve():
    # The deck height is the LiDAR deck surface (median per 20 m bin, minus
    # MHW) where there are returns; past the coverage it is a parabolic
    # vertical curve through the published clearance plus the deck
    # thickness at mid-span (250 m), falling at the end grade (0.05) to the
    # anchorages 450 m out
    out = _structure(lidar=_lidar())
    x, b = _deck_at(out, 100.0)
    assert abs(b["h"] - (30.0 + 0.01 * x)) < 0.05, "LiDAR deck surface above MHW"
    x, b = _deck_at(out, 650.0)
    want = 45.0 - 0.05 / (2 * 450.0) * (x - 250.0) ** 2
    assert abs(b["h"] - want) < 0.05, "fallback vertical curve"
    assert b["roof_rgb"] == [74, 74, 78] and b["fixed_color"] == [1, 2, 3]
    xs = [p[0] for p in _decks(out)]
    assert min(xs) < -190 and max(xs) > 690, "deck runs anchorage to anchorage"
    assert all(9.0 < b - a < 11.0 for a, b in zip(xs, xs[1:])), "~10 m steps"


def test_without_lidar_the_whole_deck_is_the_vertical_curve():
    out = _structure(lidar=None)
    x, b = _deck_at(out, 250.0)
    assert abs(b["h"] - (45.0 - 0.05 / 900.0 * (x - 250.0) ** 2)) < 0.05


def test_deck_segments_float_over_water_and_stand_on_land():
    # Water spans x -100..600. By default the suspended spans float over
    # land too (side spans hang over streets), and only the deck past the
    # anchorage front faces (x < -200, x > 700) stands on the ground;
    # land_rule "all_land" grounds every land segment
    from shapely.geometry import box

    entry = _bridge_entry(anchorage_length_m=40.0)
    out = bridges.suspension_structure(entry, _bridge_osm(), _TOWERS, lambda lon, lat: (lon, lat),
                                       water=box(-100.0, -1e3, 600.0, 1e3),
                                       lidar=_lidar(), mhw_m=_MHW)
    for x, b in _decks(out):
        if -200 < x < 700:
            assert b["z0"] > 0 and abs((b["h"] - b["z0"]) - 5.0) < 1e-6, f"suspended at {x}: deck thickness only"
        else:
            assert b["z0"] == 0, f"anchorage at {x}: solid to the ground"
    assert out["qa"]["over_water"] == 70
    out = bridges.suspension_structure(entry, _bridge_osm(), _TOWERS, lambda lon, lat: (lon, lat),
                                       water=box(-100.0, -1e3, 600.0, 1e3),
                                       lidar=_lidar(), mhw_m=_MHW, method={"land_rule": "all_land"})
    for x, b in _decks(out):
        if -95 < x < 595:
            assert b["z0"] > 0, f"over water at {x}"
        elif x < -105 or x > 605:
            assert b["z0"] == 0, f"on land at {x}: solid to the ground"


def _cables(out):
    return [t for t in out["tubes"] if "-cable-" in t["id"]]


def test_cables_end_on_the_anchorages_and_pass_over_the_tower_tops():
    out = _structure(lidar=None)
    cables = _cables(out)
    assert len(cables) == 2
    ys = sorted(round(c["pts"][0][1], 1) for c in cables)
    assert ys == [-12.5, 12.5], "one cable over each leg line"
    for c in cables:
        p = np.asarray(c["pts"])
        assert c["r"] == 0.75
        # anchorages: one side span outside each tower, at the deck top
        # there (cable_anchor_above_deck_m = 0)
        deck_end = 45.0 - 0.05 / 900.0 * 450.0 ** 2
        assert np.allclose(p[0], [-200.0, p[0][1], deck_end], atol=0.05)
        assert np.allclose(p[-1], [700.0, p[0][1], deck_end], atol=0.05)
        for tx in (0.0, 500.0):
            i = np.argmin(np.abs(p[:, 0] - tx))
            assert abs(p[i, 0] - tx) < 1e-6 and abs(p[i, 2] - 100.0) < 1e-6, "saddle on the tower top"
        assert np.all(np.diff(p[:, 0]) <= 10.0 + 1e-6), "sampled every ~10 m"


def test_cable_mid_span_sag_matches_the_config():
    out = _structure(lidar=None)
    for c in _cables(out):
        p = np.asarray(c["pts"])
        i = np.argmin(np.abs(p[:, 0] - 250.0))
        assert abs(p[i, 0] - 250.0) < 1e-6
        assert abs((100.0 - p[i, 2]) - 50.0) < 1e-6
        # side spans sag by the main sag x (side / main)^2 below the chord
        j = np.argmin(np.abs(p[:, 0] + 100.0))
        chord = (100.0 + p[0][2]) / 2
        assert abs((chord - p[j, 2]) - 50.0 * (200.0 / 500.0) ** 2) < 1e-6


def test_hangers_every_panel_from_cable_to_deck():
    out = _structure(lidar=None)
    hangers = [t for t in out["tubes"] if "-hanger-" in t["id"]]
    main = [h for h in hangers if 0 < h["pts"][0][0] < 500]
    assert len(main) == 2 * (500 // 10 - 1), "both cables, one per 10 m panel inside the main span"
    for h in hangers:
        (x0, y0, z0), (x1, y1, z1) = h["pts"]
        assert x0 == x1 and y0 == y1, "vertical"
        assert z1 > z0
        assert abs(z0 - (45.0 - 0.05 / 900.0 * (x0 - 250.0) ** 2)) < 0.05, "foot on the deck top"
        assert h["r"] == 0.3


def test_tower_crossbeams_and_x_bracing_between_the_legs():
    out = _structure(lidar=None)
    struts = [b for b in out["buildings"] if "-strut-" in b["id"]]
    assert len(struts) == 4, "two struts on each tower"
    assert sorted({(b["z0"], b["h"]) for b in struts}) == [(60.0, 62.0), (95.0, 99.0)]
    from shapely.geometry import Polygon
    for b in struts:
        g = Polygon(b["polys"][0][0])
        minx, miny, maxx, maxy = g.bounds
        assert abs(miny + 12.5) < 0.01 and abs(maxy - 12.5) < 0.01, "leg center to leg center"
        assert abs((maxx - minx) - 3.0) < 0.01
    braces = [t for t in out["tubes"] if "-brace-" in t["id"]]
    assert len(braces) == 4, "one X (two members) in the panel between the struts, per tower"
    out = _structure(entry=_bridge_entry(x_bracing=False), lidar=None)
    assert not [t for t in out["tubes"] if "-brace-" in t["id"]]


def test_lane_lines_sit_on_the_deck_inside_the_roadway():
    out = _structure(lidar=None)
    lanes = [b for b in out["buildings"] if "-lane-" in b["id"]]
    assert lanes and len(out["buildings"]) < 3000
    from shapely.geometry import Polygon
    decks = _decks(out)
    for b in lanes[::25]:
        g = Polygon(b["polys"][0][0])
        assert abs(g.centroid.y) <= 12.0 + 1e-6, "inside the 24 m roadway"
        assert b["fixed_color"] == [230, 230, 225]
        deck = min(decks, key=lambda p: abs(p[0] - g.centroid.x))[1]
        assert abs(b["z0"] - deck["h"]) < 1e-6 and abs(b["h"] - deck["h"] - 0.1) < 1e-6
    ys = sorted({round(Polygon(b["polys"][0][0]).centroid.y, 2) for b in lanes})
    assert len(ys) == 8, "6 dashed lines between 7 lanes plus 2 solid edge lines"


def test_truss_only_when_configured():
    assert not [t for t in _structure(lidar=None)["tubes"] if "-truss-" in t["id"]]
    out = _structure(entry=_bridge_entry(truss_depth_m=8.0, truss_radius_m=0.35), lidar=None)
    truss = [t for t in out["tubes"] if "-truss-" in t["id"]]
    chords = [t for t in truss if len(t["pts"]) > 2]
    assert len(chords) == 4, "top and bottom chord on each truss line"
    for c in chords:
        p = np.asarray(c["pts"])
        deck = 45.0 - 0.05 / 900.0 * (p[:, 0] - 250.0) ** 2
        off = p[:, 2] - deck
        assert np.allclose(off, 0.0, atol=0.05) or np.allclose(off, 8.0, atol=0.05)
    diags = [t for t in truss if len(t["pts"]) == 2]
    assert len(diags) > 2 * (500 // 10)
    assert all(abs(abs(d["pts"][1][2] - d["pts"][0][2]) - 8.0) < 1.0 for d in diags), "Warren zig-zag"


def test_patco_beds_and_anchorage_blocks_when_configured():
    out = _structure(entry=_bridge_entry(patco_tracks=2, patco_bed_width_m=4.0, patco_rgb=[104, 98, 92],
                                         anchorage_length_m=40.0, anchorage_width_m=50.0, anchorage_rise_m=5.0),
                     lidar=None)
    patco = [b for b in out["buildings"] if "-patco-" in b["id"]]
    assert patco and all(b["roof_rgb"] == [104, 98, 92] for b in patco)
    anch = [b for b in out["buildings"] if "-anchorage-" in b["id"]]
    assert len(anch) == 4, "a block each side of the roadway at each end"
    deck_end = 45.0 - 0.05 / 900.0 * 450.0 ** 2
    assert all(b["z0"] == 0 and abs(b["h"] - (deck_end + 5.0)) < 0.05 for b in anch)
    xs = [p[0] for p in _decks(out)]
    assert min(xs) < -230 and max(xs) > 730, "the deck runs over the anchorages"


def test_ids_are_prefixed_with_the_entry():
    out = _structure(lidar=None)
    assert all(x["id"].startswith("bridge-test-") for x in out["buildings"] + out["tubes"])
    assert len({x["id"] for x in out["buildings"] + out["tubes"]}) == len(out["buildings"]) + len(out["tubes"])


def test_missing_osm_ways_raise():
    import pytest

    osm = [e for e in _bridge_osm() if e["id"] != 99]
    with pytest.raises(KeyError):
        bridges.suspension_structure(_bridge_entry(), osm, _TOWERS, lambda lon, lat: (lon, lat))
    osm = [e for e in _bridge_osm() if e["id"] != 2]
    with pytest.raises(KeyError):
        bridges.suspension_structure(_bridge_entry(), osm, _TOWERS, lambda lon, lat: (lon, lat))


def test_suspension_structures_for_is_a_no_op_without_the_flag():
    assert bridges.suspension_structures_for({"name": "south_lidar"}, None) == {"buildings": [], "tubes": []}


def test_every_bridge_structure_value_is_sourced_or_an_estimate_with_a_reason():
    import json

    from pixelphilly.projection import REPO_ROOT

    conf = json.loads((REPO_ROOT / "config" / "bridge_structures.json").read_text())
    assert "ODbL" in conf["about"] and "PASDA" in conf["about"]
    vals = [conf["datum"]["mhw_navd88_m"]] + [d for e in conf["entries"] for d in e["dims"].values()]
    assert {e["id"] for e in conf["entries"]} == {"ben_franklin", "walt_whitman"}
    for d in vals:
        assert "value" in d, d
        if d.get("estimate"):
            assert len(d.get("reason", "")) > 10, d
        else:
            assert str(d.get("source", "")).startswith("https://"), d
    towers = {e["id"] for e in json.loads((REPO_ROOT / "config" / "bridge_towers.json").read_text())["entries"]}
    assert all(set(e["tower_entries"]) <= towers for e in conf["entries"])


def test_npz_window_streams_the_same_cells_as_a_full_load(tmp_path):
    # The area grids are ~1.2 GB per array compressed; the window reader
    # streams rows instead of loading the whole array
    rng = np.random.default_rng(0)
    dsm = rng.normal(size=(300, 200)).astype(np.float32)
    path = tmp_path / "g.npz"
    np.savez_compressed(path, dsm=dsm, ground=dsm, origin=np.array([-50.0, 75.0]))
    w = bridges.npz_window(path, "dsm", (-30.0, 0.0, 10.0, 40.0), 0.5)  # cols 40-120, rows 70-150
    assert w["origin"] == (-30.0, 40.0)
    assert np.array_equal(w["dsm"], dsm[70:150, 40:120])
    assert bridges.npz_window(path, "dsm", (500.0, 500.0, 600.0, 600.0), 0.5) is None


# --- Approach decks past the anchorages (Nov. 9, wiring) ---
# The modeled deck used to stop at the anchorages while the LiDAR shows the
# approaches still descending (the Walt Whitman is ~37 m up 400 m past its PA
# anchorage). Synthetic bridge as above, now with two OSM carriageways at
# y = +/-6 from x = -900 to x = 1000, and a LiDAR deck flat at 30 m above
# MHW over the spans, falling 0.05 m/m past the anchorage at x = -200 onto
# ground at 4 m NAVD88. No returns past x = 700 (like the Walt Whitman's NJ
# end), so that end falls back to a configured grade.

_APPROACH = {"pier_spacing_m": 50.0, "pier_length_m": 3.0, "deck_thickness_m": 2.0, "stop_above_ground_m": 2.0,
             "fallback_grade": 0.04, "datum_blend_m": 100.0, "ground_radius_m": 40.0, "max_spread_m": 40.0,
             "pier_rgb": [150, 148, 140]}


def _approach_osm(x_end=1000.0):
    strip = lambda x: [(x - 2.5, -15.0), (x + 2.5, -15.0), (x + 2.5, 15.0), (x - 2.5, 15.0)]
    ways = [{"type": "way", "id": 99 + k, "tags": {"highway": "motorway", "bridge": "yes", "lanes": "3"},
             "geometry": [{"lon": -900.0, "lat": y}, {"lon": x_end, "lat": y}]} for k, y in ((0, 6.0), (1, -6.0))]
    return [_tower_osm(1, strip(0.0)), _tower_osm(2, strip(500.0))] + ways


def _approach_grids():
    res, west, north = 0.5, -1000.0, 80.0
    cols, rows = 4400, 320
    x = west + (np.arange(cols) + 0.5) * res
    y = north - (np.arange(rows) + 0.5) * res
    deck = np.where(x < -200.0, _MHW + 30.0 - 0.05 * (-200.0 - x), _MHW + 30.0)
    on_deck = np.abs(y)[:, None] <= 15.0
    dsm = np.where(on_deck, deck[None, :], 4.0)
    dsm = np.where(x[None, :] < 700.0, dsm, np.nan).astype(np.float32)
    # Ground returns only beside the deck (the deck hides the ground under it)
    ground = np.where(on_deck | (x[None, :] >= 700.0), np.nan, 4.0).astype(np.float32)
    return ({"dsm": dsm, "origin": (west, north), "res": res},
            {"dsm": ground, "origin": (west, north), "res": res})


def _approach_structure(approach=True, **over):
    from shapely.geometry import box

    entry = _bridge_entry(**over)
    entry["osm_deck_ways"] = [99, 100]
    if approach:
        entry["approach"] = True
    dsm, ground = _approach_grids()
    return bridges.suspension_structure(entry, _approach_osm(), _TOWERS, lambda lon, lat: (lon, lat),
                                        water=box(-100.0, -1000.0, 600.0, 1000.0), lidar=dsm, ground=ground,
                                        mhw_m=_MHW, method={"approach": dict(_APPROACH)})


def _parts(out, part):
    from shapely.geometry import Polygon

    return sorted(((Polygon(b["polys"][0][0]).centroid.x, b) for b in out["buildings"] if f"-{part}-" in b["id"]),
                  key=lambda p: p[0])


def test_approach_deck_follows_the_lidar_profile_above_local_ground():
    out = _approach_structure()
    app = _parts(out, "approach")
    assert app, "approach decks past the anchorages"
    # 200 m out (past the 100 m datum blend) the deck is the LiDAR surface
    # minus the local ground (4 m NAVD88), like every building on land
    x, b = min(app, key=lambda p: abs(p[0] + 400.0))
    want = _MHW + 30.0 - 0.05 * (-200.0 - x) - 4.0
    assert abs(b["h"] - want) < 0.3, (x, b["h"], want)
    assert abs((b["h"] - b["z0"]) - 2.0) < 1e-6, "floats on the approach deck thickness"
    assert b["roof_rgb"] == [74, 74, 78]
    # At the anchorage the datum is still mean high water, so the approach
    # meets the main deck without a step
    x, b = max((p for p in app if p[0] < 0), key=lambda p: p[0])
    assert abs(b["h"] - 30.0) < 0.6, (x, b["h"])
    from shapely.geometry import Polygon
    ys = Polygon(b["polys"][0][0]).bounds
    assert abs(ys[1] + 15.0) < 0.1 and abs(ys[3] - 15.0) < 0.1, "as wide as the main deck past the carriageways"


def test_approach_stops_where_the_deck_reaches_the_ground():
    out = _approach_structure()
    xs = [p[0] for p in _parts(out, "approach") if p[0] < 0]
    # 31 - 0.05 d - 4 = 2 m above ground at d = 500 m past x = -200
    assert -715.0 < min(xs) < -685.0, min(xs)
    qa = out["qa"]["approach"]
    assert qa["a"]["end"] == "at_grade" and qa["b"]["end"] == "osm_end"


def test_approach_without_lidar_falls_back_to_the_grade_and_stops_at_the_osm_end():
    out = _approach_structure()
    app = [p for p in _parts(out, "approach") if p[0] > 500]
    assert max(p[0] for p in app) > 990.0 - 10.0 and max(p[0] for p in app) < 1000.0
    x, b = min(app, key=lambda p: abs(p[0] - 850.0))
    assert abs(b["h"] - (30.0 - 0.04 * (x - 700.0))) < 0.6, (x, b["h"])
    assert out["qa"]["approach"]["b"]["fallback_segments"] > 0


def test_approach_piers_every_pier_spacing_under_the_floating_deck():
    from shapely.geometry import Polygon

    out = _approach_structure()
    piers = [p for p in _parts(out, "pier") if p[0] < 0]
    xs = [p[0] for p in piers]
    assert len(xs) >= 8
    assert np.allclose(np.diff(xs), 50.0, atol=0.01), "one pier every 50 m"
    app = _parts(out, "approach")
    for x, b in piers:
        assert b["z0"] == 0, "piers stand on the ground"
        deck = min(app, key=lambda p: abs(p[0] - x))[1]
        assert b["h"] <= deck["z0"] + 1e-6 and b["h"] > deck["z0"] - 1.0, "up to the deck underside"
        minx, miny, maxx, maxy = Polygon(b["polys"][0][0]).bounds
        assert abs((maxx - minx) - 3.0) < 0.05 and abs((maxy - miny) - 30.0) < 0.1, "deck width x 3 m"


def test_approach_lane_lines_and_sane_counts():
    out = _approach_structure()
    lanes = [b for b in out["buildings"] if "-approach_lane-" in b["id"]]
    assert lanes
    app = _parts(out, "approach")
    from shapely.geometry import Polygon
    for b in lanes[::20]:
        g = Polygon(b["polys"][0][0])
        deck = min(app, key=lambda p: abs(p[0] - g.centroid.x))[1]
        assert abs(b["z0"] - deck["h"]) < 1e-6
    ys = sorted({round(Polygon(b["polys"][0][0]).centroid.y, 1) for b in lanes})
    # 3 lanes per carriageway at 3.6 m: edges at +/-5.4 and dashes at +/-1.8 around y = +/-6
    assert ys == [-11.2, -7.8, -4.2, -0.8, 0.8, 4.2, 7.8, 11.2], ys
    assert len(out["buildings"]) < 6000 and len(out["tubes"]) < 1000


def test_no_approach_without_the_entry_flag():
    out = _approach_structure(approach=False)
    assert not _parts(out, "approach") and not _parts(out, "pier")
    assert "approach" not in out["qa"]


def test_structure_repeats_no_tower_legs():
    out = _approach_structure()
    assert not [b for b in out["buildings"] if b["id"].startswith("tower-") or "-leg" in b["id"]]


# --- Ground under the raised decks ---

def test_deck_plan_covers_deck_and_approach_segments_only():
    out = _approach_structure()
    plan = bridges.deck_plan(out["buildings"], margin_m=2.0)
    assert plan.contains(__import__("shapely").geometry.Point(250.0, 16.5)), "deck plus 2 m"
    assert plan.contains(__import__("shapely").geometry.Point(-500.0, 0.0)), "approach"
    assert not plan.contains(__import__("shapely").geometry.Point(250.0, 18.0))


def test_paint_out_fills_water_with_river_and_land_with_its_neighbors():
    rng = np.random.default_rng(5)
    H, W = 200, 300
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[:100] = (108, 101, 64)  # river
    rgb[100:] = (150, 140, 120)  # land
    rgb = np.clip(rgb.astype(int) + rng.integers(-4, 5, rgb.shape), 0, 255).astype(np.uint8)
    rgb[:, 140:160] = (60, 60, 64)  # the photo deck, over river and land
    water = np.zeros((H, W), bool)
    water[:100] = True
    hole = np.zeros((H, W), bool)
    hole[:, 138:162] = True
    rgb[:100, 162:167] = (205, 205, 195)  # the photo deck's lit railing, just outside the hole
    out = bridges.paint_out_decks(rgb, hole, water)
    assert np.abs(out[10:90, 140:160].astype(int) - (108, 101, 64)).max() < 10, "river under the deck, untinted"
    assert np.abs(out[110:190, 140:160].astype(int) - (150, 140, 120)).max() < 10, "land under the deck"
    assert (out[~hole] == rgb[~hole]).all(), "nothing outside the hole changes"


# --- Repaint: structure bridges leave the band for a protection region ---

def test_structure_corridor_clips_band_lines_on_the_modeled_bridges_only():
    from shapely.geometry import box

    corr = bridges.structure_corridor([dict(_bridge_entry(), osm_deck_ways=[99, 100])], _approach_osm(),
                                      lambda lon, lat: (lon, lat))
    water = box(-100.0, -1000.0, 600.0, 1000.0)
    lines = [(LineString([(-900, 0), (1000, 0)]), 14.0),  # the modeled bridge (e.g. City centerline)
             (LineString([(-900, 400), (1000, 400)]), 10.0)]  # a third bridge, not in the config
    band = bridges.deck_geometry(bridges.clip_lines(lines, corr), water)
    assert not band.is_empty
    assert band.distance(LineString([(-100, 0), (600, 0)])) > 20, "no band on the modeled bridge"
    assert band.contains(__import__("shapely").geometry.Point(250, 400)), "the third bridge keeps its band"


def _cam():
    from pixelphilly.projection import IsoCamera

    return IsoCamera(54.0, 45.0, 0.293)


def test_structure_protection_covers_cables_hangers_and_deck_but_not_open_river():
    from shapely.geometry import Point

    out = _structure(lidar=None)
    legs = bridges.tower_legs(_bridge_osm(), _TOWERS, lambda lon, lat: (lon, lat))
    cam = _cam()
    prot = bridges.structure_protect(out["buildings"], out["tubes"], legs, cam, 0.0, 0.0)

    def scr(e, n, z):
        x, y = cam.world_to_screen(e, n, z)
        return Point(float(x), float(y))

    cable = _cables(out)[0]
    p = np.asarray(cable["pts"])[len(cable["pts"]) // 3]
    assert prot.contains(scr(*p)), "cable"
    deck_top = 45.0 - 0.05 / 900.0 * (p[0] - 250.0) ** 2
    assert prot.contains(scr(p[0], p[1], (p[2] + deck_top) / 2)), "between cable and deck: hangers"
    assert prot.contains(scr(250.0, 0.0, 42.0)), "deck"
    assert prot.contains(scr(0.0, 12.5, 80.0)), "tower leg"
    assert not prot.contains(scr(250.0, 300.0, 0.0)), "open river beside the bridge"
    assert not prot.contains(scr(250.0, -300.0, 0.0))
    # Tight shape, not the whole sweep from the water to the tower tops: the
    # river 20 m under the mid-span deck, seen past it, is not covered
    assert not prot.contains(scr(250.0, 0.0, 10.0))


def test_structure_zones_split_solid_prisms_from_cables_and_hanger_zone():
    from shapely.geometry import Point

    out = _structure(lidar=None)
    legs = bridges.tower_legs(_bridge_osm(), _TOWERS, lambda lon, lat: (lon, lat))
    cam = _cam()
    solid, members = bridges.structure_zones(out["buildings"], out["tubes"], legs, cam, 0.0, 0.0)

    def scr(e, n, z):
        x, y = cam.world_to_screen(e, n, z)
        return Point(float(x), float(y))

    cable = _cables(out)[0]
    p = np.asarray(cable["pts"])[len(cable["pts"]) // 3]
    deck_top = 45.0 - 0.05 / 900.0 * (p[0] - 250.0) ** 2
    assert solid.contains(scr(250.0, 0.0, 42.0)) and not members.contains(scr(250.0, 0.0, 42.0)), "deck"
    assert solid.contains(scr(0.0, 12.5, 80.0)), "tower leg"
    assert members.contains(scr(*p)) and not solid.contains(scr(*p)), "cable"
    hz = scr(p[0], p[1], (p[2] + deck_top) / 2)
    assert members.contains(hz) and not solid.contains(hz), "hanger zone"
    assert solid.intersection(members).area < 1e-6, "disjoint"
    whole = bridges.structure_protect(out["buildings"], out["tubes"], legs, cam, 0.0, 0.0)
    assert abs(whole.area - solid.area - members.area) < 1e-3, "structure_protect is their union"
