"""Wiring of the suspension-bridge structures (Ben Franklin, Walt Whitman)
into the scene build (scripts/05_build_scene.py) and the water repaint
(scripts/10_repaint_water.py). Synthetic data only: the real builds take
over an hour."""

import importlib.util

import numpy as np
from PIL import Image
from shapely.geometry import Point, box

from pixelphilly import waterpaint
from pixelphilly.projection import REPO_ROOT


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_scene = _load("build_scene_w", "05_build_scene.py")
repaint = _load("repaint_w", "10_repaint_water.py")

RING = [[0.0, -15.0], [10.0, -15.0], [10.0, 15.0], [0.0, 15.0]]


def _structures():
    deck = {"id": "bridge-bfb-deck-0", "h": 45.0, "z0": 40.0, "polys": [[RING]], "fixed_color": [1, 2, 3],
            "roof_rgb": [74, 74, 78]}
    lane = {"id": "bridge-bfb-lane-1", "h": 45.1, "z0": 45.0, "polys": [[RING]], "fixed_color": [230, 230, 225]}
    tube = {"id": "bridge-bfb-cable-2", "pts": [[0, 0, 50], [10, 0, 48]], "r": 0.75, "color": [1, 2, 3]}
    return {"buildings": [deck, lane], "tubes": [tube],
            "qa": {"bfb": {"segments": 1, "approach": {"a": {"segments": 3}}}}}


def test_add_bridge_structures_appends_buildings_and_tubes_and_reports_counts(capsys):
    buildings, tubes = [{"id": "1-0", "h": 9.0, "polys": [[RING]]}], []
    qa = build_scene.add_bridge_structures({"name": "x"}, None, buildings, tubes, structures=_structures())
    assert [b["id"] for b in buildings] == ["1-0", "bridge-bfb-deck-0", "bridge-bfb-lane-1"]
    assert [t["id"] for t in tubes] == ["bridge-bfb-cable-2"]
    assert qa["bridge_structures"]["bfb"]["buildings"] == 2 and qa["bridge_structures"]["bfb"]["tubes"] == 1
    assert "bridge structure: bfb buildings 2 tubes 1" in capsys.readouterr().out


def test_add_bridge_structures_is_a_no_op_without_structures():
    buildings, tubes = [], []
    assert build_scene.add_bridge_structures({"name": "x"}, None, buildings, tubes,
                                             structures={"buildings": [], "tubes": []}) == {}
    assert buildings == [] and tubes == []


def test_bridge_structures_reach_the_scene_with_z0_and_roof_rgb():
    out = build_scene.colored(_structures()["buildings"], ground=None, cfg={})
    assert out[0]["z0"] == 40.0 and out[0]["roof_rgb"] == [74, 74, 78]


def _ground(H=200, W=300):
    rng = np.random.default_rng(1)
    arr = np.zeros((H, W, 3), np.uint8)
    arr[:100] = (108, 101, 64)
    arr[100:] = (150, 140, 120)
    arr = np.clip(arr.astype(int) + rng.integers(-4, 5, arr.shape), 0, 255).astype(np.uint8)
    arr[:, 140:160] = (60, 60, 64)  # the photo deck
    # Identity-ish texture: 1 px per m, row 0 at n = 200
    return {"ground": Image.fromarray(arr), "to_px_arr": lambda e, n: (np.asarray(e, float), H - np.asarray(n, float))}


def test_deck_ground_paints_out_the_photo_deck_under_the_raised_deck():
    g = _ground()
    before = np.asarray(g["ground"]).copy()
    plan = box(140.0, 0.0, 160.0, 200.0)  # the deck in plan, local m
    water = box(0.0, 100.0, 300.0, 200.0)  # top half of the texture
    qa = build_scene.paint_deck_ground(g, plan, water)
    after = np.asarray(g["ground"])
    assert qa["bridge_deck_ground_px"] > 0
    assert np.abs(after[10:90, 142:158].astype(int) - (108, 101, 64)).max() < 10, "river"
    assert np.abs(after[110:190, 142:158].astype(int) - (150, 140, 120)).max() < 10, "land"
    assert (after[:, :130] == before[:, :130]).all() and (after[:, 170:] == before[:, 170:]).all()


def test_deck_ground_outside_the_texture_changes_nothing():
    g = _ground()
    before = np.asarray(g["ground"]).copy()
    qa = build_scene.paint_deck_ground(g, box(1000.0, 1000.0, 1100.0, 1100.0), box(0, 0, 1, 1))
    assert qa == {"bridge_deck_ground_px": 0}
    assert (np.asarray(g["ground"]) == before).all()


# --- Repaint ---

def test_never_repaint_grows_the_mask_more_near_the_structure_only():
    span = 100
    mask = np.zeros((span, span), bool)
    mask[20, 20] = True  # far from the structure
    mask[60, 60] = True  # next to it
    struct = box(64.0, 0.0, 100.0, 100.0)  # mosaic px
    out = repaint.never_repaint(mask, None, struct, 0, 0, span)
    assert out[20, 22] and not out[20, 23], "default 5 px window (2 px) away from the structure"
    assert out[60, 52] and not out[60, 51], "8 px around the structure"
    assert out[:, 64:].all(), "the structure's region is never repainted"


def test_drawn_cable_over_water_inside_the_protection_is_kept_and_open_river_repaints():
    river = np.array([108, 101, 64])
    span = 120
    render = np.tile(river, (span, span, 1)).astype(np.uint8)  # the render: all river (deck sits high above)
    nhd = np.ones((span, span), bool)
    struct = box(40.0, 40.0, 80.0, 80.0)  # sweep of deck, cables and hangers on screen
    bmask = repaint.never_repaint(np.zeros((span, span), bool), None, struct, 0, 0, span)
    water = waterpaint.water_mask(render, nhd, bmask, river.astype(float), 68.0)
    assert not water[60, 60], "a drawn cable or truss pixel inside the sweep keeps the drawing"
    assert water[10, 10] and water[110, 110], "open river outside it is repainted"


def test_hanger_zone_repaints_drawn_river_and_keeps_strokes_deck_and_other_bands():
    """Nov. 9 review: a tan band filled the zone between each main cable and
    the deck on the BFB and WWB. The model draws the river there in its raw
    colors between the hangers; the members zone must take river-colored
    pixels and keep the drawn strokes, while the deck prism stays as drawn
    whatever its color and a bridge outside the config keeps its band."""
    from pixelphilly import bridges

    brown = np.array([150, 120, 80], np.uint8)  # the drawn river
    stroke = np.array([40, 60, 90], np.uint8)  # drawn hangers and cable
    rnd = np.array([108, 101, 64])  # the render's river
    span = 200
    raw = np.tile(brown, (span, span, 1))
    render = np.tile(rnd, (span, span, 1)).astype(np.uint8)
    mask = np.zeros((span, span), bool)  # the render mask: deck and tubes
    # Deck prism, rows 100-119, cols 20-180: drawn in river brown on purpose
    solid = box(20.0, 100.0, 180.0, 120.0)
    mask[100:120, 20:180] = True
    # Members zone above it: cable at row 60, hangers every 15 px down to the deck
    members = box(20.0, 55.0, 180.0, 100.0)
    raw[59:62, 20:180] = stroke
    hangers = list(range(30, 175, 15))
    for c in hangers:
        raw[60:100, c:c + 2] = stroke
        mask[60:100, c] = True  # the render's tube, 1 px
    mask[60, 20:180] = True
    raw[80, 37] = stroke  # an isolated speck in the drawn river (ripple dash)
    # A hanger drawn in a river color (the WWB's green-gray hangers next to its
    # olive river), on the render's tube: the render mask keeps it
    raw[60:100, 172] = brown + 10
    mask[60:100, 172] = True
    # A third bridge outside the config: its band, half drawn deck, half river
    band_geom = box(20.0, 150.0, 180.0, 170.0)
    raw[150:170, 20:100] = (70, 70, 74)
    nhd = np.ones((span, span), bool)

    bmask = repaint.never_repaint(mask, None, solid, 0, 0, span, members_geom=members)
    water = waterpaint.water_mask(render, nhd, bmask, rnd.astype(float), 68.0)
    band = repaint.protected(band_geom, 0, 0, span)
    zone = repaint.protected(members, 0, 0, span)
    sample = bridges.ring_sample(water, raw, band | zone)
    assert sample is not None
    water = repaint.bridge_water(water, raw, band, None, zone, sample)

    between = [(r, c + 7) for r in (70, 85, 95) for c in hangers[:-1]]
    assert all(water[p] for p in between), "drawn river between the hangers is repainted"
    assert water[80, 37], "an isolated non-river speck is repainted too"
    assert not any(water[r, c] for r in (70, 85, 95) for c in hangers), "hanger strokes are kept"
    assert not water[60, 100:150].any(), "the cable stroke is kept"
    assert not water[85, 172], "a river-colored hanger on the render's tube is kept"
    assert not water[100:120, 20:180].any(), "the deck prism keeps the drawing, river-colored or not"
    assert not water[155:165, 25:95].any() and water[155:165, 110:175].all(), "the third bridge's band"
    assert water[10, 10] and water[190, 190], "open river"


def test_kept_strokes_in_the_members_zone_get_no_shore_band():
    """The shore band (waterpaint.apply, 4 px) along every kept hanger turned
    each 12-15 px bay between hangers into a dark-framed window (Nov. 9
    scratch run). Strokes inside the members zone stay as drawn, but the
    water beside them is plain water; outside the zone shores are unchanged."""
    span = 60
    raw = np.full((span, span, 3), 200, np.uint8)
    water = np.ones((span, span), bool)
    water[:, 30] = False  # a kept hanger stroke
    water[50:, :] = False  # land below, outside the zone
    members = np.zeros((span, span), bool)
    members[:45, :] = True
    out = repaint.paint_water(raw, water, members, 0, 0)
    base, shore = waterpaint.WATER_STYLE["base"], waterpaint.WATER_STYLE["shore"]
    assert (out[:45, 30] == 200).all(), "the stroke keeps the drawing"
    assert tuple(out[20, 29]) != shore and tuple(out[20, 31]) != shore, "no shore beside the stroke"
    assert tuple(out[20, 28]) in (base, waterpaint.WATER_STYLE["ripple"])
    assert tuple(out[48, 10]) == shore, "the shore along land is unchanged"


def test_tubes_near_the_deck_get_no_8px_grow_outside_the_members_zone():
    """Where the cable nears the deck, the tubes' 8 px grow (meant for the
    solid parts) reached past the members zone and kept a sliver of raw river
    above the cable (Nov. 9 scratch run, WWB mid-span)."""
    span = 100
    mask = np.zeros((span, span), bool)
    mask[50:60, :] = True  # deck
    mask[44, :] = True  # cable tube, 6 px above it
    solid = box(0.0, 50.0, 100.0, 60.0)
    members = box(0.0, 42.0, 100.0, 50.0)
    out = repaint.never_repaint(mask, None, solid, 0, 0, span, members_geom=members)
    assert out[44, 50] and out[50:60].all(), "tube (1 px grow) and deck kept"
    assert not out[38:42, 50].any(), "no grow from the tube past the zone"
