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
