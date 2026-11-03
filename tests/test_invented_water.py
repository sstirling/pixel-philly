"""Invented water on land: blobs of water-colored pixels the drawing model put
on open ground (a blue pool in a shaded courtyard beside City Hall)."""

import numpy as np

from pixelphilly import invented_water as iw

POOL = (114, 163, 181)  # measured: the invented pool, atlas_cityhall_fac frame_01_01
GROUND = (150, 140, 128)
BUILDING = (120, 90, 80)


def _scene(blob_size=40):
    h, w = 200, 200
    drawing = np.zeros((h, w, 3), np.uint8)
    drawing[:] = GROUND
    drawing[60:60 + blob_size, 60:60 + blob_size] = POOL
    render = np.zeros_like(drawing)
    render[:] = (100, 98, 96)  # shaded pavement in the aerial
    water_ok = np.zeros((h, w), bool)
    buildings = np.zeros((h, w), bool)
    return drawing, render, water_ok, buildings


def test_water_like_band_covers_the_pool_and_the_repaint_style_not_ground():
    from pixelphilly.waterpaint import WATER_STYLE

    px = np.array([[POOL, WATER_STYLE["base"], WATER_STYLE["ripple"], WATER_STYLE["shore"], GROUND, BUILDING,
                    (70, 110, 60), (200, 200, 200), (80, 92, 104)]], np.uint8)
    # The last: shaded blue-gray pavement (V 0.41, S 0.23), the dry run's false positive
    assert iw.water_like(px).tolist() == [[True, True, True, True, False, False, False, False, False]]


def test_a_pool_on_open_ground_is_flagged():
    drawing, render, water_ok, buildings = _scene()
    blobs = iw.find_blobs(drawing, render, water_ok, buildings)
    assert len(blobs) == 1 and blobs[0]["area_px"] == 1600 and blobs[0]["bbox"] == [60, 60, 100, 100]
    assert blobs[0]["exempt"] is None


def test_small_blobs_water_and_buildings_are_not_flagged():
    drawing, render, water_ok, buildings = _scene(blob_size=15)  # 225 px < 400
    assert iw.find_blobs(drawing, render, water_ok, buildings) == []
    drawing, render, water_ok, buildings = _scene()
    water_ok[40:120, 40:120] = True  # inside NHD/PWD water (grown)
    assert iw.find_blobs(drawing, render, water_ok, buildings) == []
    drawing, render, water_ok, buildings = _scene()
    buildings[50:110, 50:110] = True  # a glass curtain wall is a building
    assert iw.find_blobs(drawing, render, water_ok, buildings) == []


def test_real_pools_and_fountains_are_exempt():
    drawing, render, water_ok, buildings = _scene()
    render[60:100, 60:100] = (90, 120, 135)  # the aerial shows water there (a fountain)
    blobs = iw.find_blobs(drawing, render, water_ok, buildings)
    assert blobs[0]["exempt"] == "render shows water"
    # Shaded gray pavement in the aerial is not water (the City Hall courtyard)
    drawing, render, water_ok, buildings = _scene()
    render[60:100, 60:100] = (72, 74, 70)
    assert iw.find_blobs(drawing, render, water_ok, buildings)[0]["exempt"] is None
    drawing, render, water_ok, buildings = _scene()
    blobs = iw.find_blobs(drawing, render, water_ok, buildings, pools_px=[(85, 75)], pool_radius_px=85)
    assert blobs[0]["exempt"] == "city pool"


def test_repair_fills_the_blob_flat_from_the_surrounding_drawing():
    # Flat fill: the ring's typical color (an actual drawing color). A
    # palette-mapped fill of the aerial's texture left noisy dark blotches
    drawing, render, water_ok, buildings = _scene()
    drawing[50:60, :] = (90, 85, 80)  # a darker band nearby
    render[60:80, 60:100] = (60, 58, 55)
    blobs = iw.find_blobs(drawing, render, water_ok, buildings)
    out = iw.repair(drawing, render, blobs)
    blob = np.zeros(drawing.shape[:2], bool)
    blob[60:100, 60:100] = True
    assert np.array_equal(out[~blob], drawing[~blob]), "only blob pixels change"
    colors = {tuple(c) for c in out[blob].reshape(-1, 3)}
    assert colors == {GROUND}, colors


def test_repair_takes_ripple_dashes_and_the_blue_fringe_too():
    drawing, render, water_ok, buildings = _scene()
    drawing[70:71, 70:74] = (240, 245, 245)  # a ripple dash the model drew (a 4 px hole in the blob)
    drawing[59, 60:100] = (140, 150, 156)  # an antialiased bluish edge row (S 0.10)
    drawing[80:92, 80:92] = BUILDING  # a real object inside (144 px): stays
    out = iw.repair(drawing, render, iw.find_blobs(drawing, render, water_ok, buildings))
    assert tuple(out[70, 71]) == GROUND and tuple(out[59, 70]) == GROUND
    assert tuple(out[85, 85]) == BUILDING
    assert not iw.water_like(out).any()


def test_blobs_on_nwi_wetlands_are_exempt():
    # Lower South Philly basins and mudflats: possibly real water missing
    # from NHD and PWD. A blob 20% or more inside an NWI wetland stays
    drawing, render, water_ok, buildings = _scene()
    wet = np.zeros(drawing.shape[:2], bool)
    wet[60:70, 60:100] = True  # 25% of the blob
    assert iw.find_blobs(drawing, render, water_ok, buildings, wetlands=wet)[0]["exempt"] == "NWI wetland"
    wet[:] = False
    wet[60:65, 60:100] = True  # 12.5%: just touching
    assert iw.find_blobs(drawing, render, water_ok, buildings, wetlands=wet)[0]["exempt"] is None


def test_flat_light_rectangles_are_missing_roofs_not_water():
    # Upper North: a gym's light-blue roof, its building missing from the
    # scene (rectangularity 0.88; aerial V 0.76, flat, gray)
    drawing, render, water_ok, buildings = _scene()
    render[60:100, 60:100] = (190, 194, 196)
    assert iw.find_blobs(drawing, render, water_ok, buildings)[0]["exempt"] == "roof-like (building missing)"
    # A roof section partly hidden behind a building drawn in front (rectangularity ~0.8), with vents
    drawing, render, water_ok, buildings = _scene()
    drawing[60:72, 88:100] = BUILDING  # a corner cut out by a foreground building
    render[60:100, 60:100] = (190, 194, 196)
    render[80:82, 64:96:4] = (120, 124, 126)  # vents
    assert iw.find_blobs(drawing, render, water_ok, buildings)[0]["exempt"] == "roof-like (building missing)"
    drawing, render, water_ok, buildings = _scene()
    render[60:100, 60:100] = (190, 194, 196)
    # The same rectangle over dark green turf (the South Philly field drawn as a pool) is water to fix
    render[60:100, 60:100] = (98, 112, 60)
    assert iw.find_blobs(drawing, render, water_ok, buildings)[0]["exempt"] is None
    # An irregular blob over a light flat aerial (a courtyard) is not a roof
    drawing, render, water_ok, buildings = _scene()
    drawing[60:100, 60:100] = GROUND
    yy, xx = np.mgrid[0:200, 0:200]
    blob = ((xx - 80) ** 2 + (yy - 80) ** 2 < 22 ** 2) & ~((xx > 80) & (yy > 80))  # a three-quarter disc
    drawing[blob] = POOL
    render[blob] = (190, 194, 196)
    assert iw.find_blobs(drawing, render, water_ok, buildings)[0]["exempt"] is None


def test_green_aerial_fills_with_the_drawings_green():
    # The turf field: the ring median was gray; where the aerial is clearly
    # green, the fill is the ring's green
    drawing, render, water_ok, buildings = _scene()
    drawing[100:110, :] = (70, 120, 60)  # drawn grass below the blob
    render[60:100, 60:100] = (98, 112, 60)
    out = iw.repair(drawing, render, iw.find_blobs(drawing, render, water_ok, buildings))
    assert tuple(out[80, 80]) == (70, 120, 60)
    # A non-green aerial keeps the ring's typical color
    render[60:100, 60:100] = (120, 112, 96)
    out = iw.repair(drawing, render, iw.find_blobs(drawing, render, water_ok, buildings))
    assert tuple(out[80, 80]) == GROUND


def test_held_blobs_are_logged_but_not_repaired():
    # Reviewed hold list (Stephen, Oct. 27): blobs we can't verify as invented
    # (lower South Philly mudflats, a real blue court, a light-blue roof) are
    # marked held with the reason, so repair leaves them as drawn
    from pixelphilly.invented_water import apply_holds

    blobs = [{"bbox": [10, 10, 30, 30], "area_px": 400, "exempt": None},
             {"bbox": [200, 200, 240, 240], "area_px": 1600, "exempt": None},
             {"bbox": [500, 500, 520, 520], "area_px": 400, "exempt": "city pool"}]
    holds = [{"bbox": [1100, 1100, 1300, 1300], "reason": "mudflat, unverified"}]
    out = apply_holds(blobs, gx=1000, gy=1000, holds=holds)  # blob 2's global center (1220, 1220) is held
    assert out[0]["exempt"] is None
    assert out[1]["exempt"] == "held: mudflat, unverified"
    assert out[2]["exempt"] == "city pool"  # existing exemptions are kept
    assert apply_holds(blobs, 0, 0, []) == blobs


def _hsv_rgb(h, s, v):
    import colorsys
    return [round(c * 255) for c in colorsys.hsv_to_rgb(h / 360, s, v)]


def test_turf_fill_uses_a_real_lawn_green():
    # The South Philly turf field came out gray-teal: the ring's "greens"
    # included a teal-gray (hue 157, sat 0.15). A real drawn lawn elsewhere in
    # the window is the right fill when the aerial under the blob is green
    from pixelphilly.invented_water import repair

    d = np.zeros((200, 200, 3), np.uint8)
    d[:] = _hsv_rgb(35, 0.30, 0.80)  # tan ground
    d[150:, :60] = _hsv_rgb(100, 0.45, 0.55)  # a drawn lawn elsewhere in the window
    d[60:110, 60:110] = _hsv_rgb(197, 0.37, 0.71)  # invented pool on the turf
    d[55:60, 60:110] = [136, 161, 152]  # teal-gray edge in the ring
    r = np.zeros_like(d)
    r[:] = _hsv_rgb(61, 0.38, 0.44)  # dormant turf in the aerial
    mask = np.zeros((200, 200), bool)
    mask[60:110, 60:110] = True
    out = repair(d, r, [{"bbox": [0, 0, 200, 200], "mask_bbox": mask, "exempt": None}])
    fill = out[85, 85].astype(int)
    assert fill[1] > fill[0] and fill[1] > fill[2], fill  # green dominant
    assert abs(fill.tolist()[0] - 136) > 20, "not the teal-gray"


def test_invented_lawn_in_a_paved_courtyard_is_found():
    # City Hall (v5): the AI drew grass in the paved courtyard. A courtyard is
    # a hole in ONE building's footprint (rowhouse block interiors are
    # separate backyards, real lawns); flagged only where the aerial is paving
    from pixelphilly.invented_water import courtyard_lawn

    d = np.zeros((300, 300, 3), np.uint8)
    d[:] = _hsv_rgb(30, 0.10, 0.60)  # paving
    b = np.zeros((300, 300), bool)
    b[50:250, 50:250] = True
    b[100:200, 100:200] = False
    holes = np.zeros((300, 300), bool)
    holes[100:200, 100:200] = True  # the footprint's courtyard hole
    d[120:180, 120:180] = _hsv_rgb(100, 0.50, 0.50)  # invented grass
    r = np.zeros_like(d)
    r[:] = _hsv_rgb(30, 0.08, 0.35)  # shadowed paving in the aerial
    blobs = courtyard_lawn(d, r, b, holes)
    assert len(blobs) == 1 and blobs[0]["bbox"][0] >= 100
    # A courtyard that is green, or dormant grass, in the aerial is left alone
    r2 = r.copy(); r2[100:200, 100:200] = _hsv_rgb(100, 0.45, 0.45)
    assert courtyard_lawn(d, r2, b, holes) == []
    r3 = r.copy(); r3[100:200, 100:200] = _hsv_rgb(48, 0.32, 0.45)
    assert courtyard_lawn(d, r3, b, holes) == []


def test_rowhouse_block_interior_is_not_a_courtyard():
    # 207 false flags on the first try: block interiors between separate
    # rowhouses, dormant brown in the March aerial, correctly drawn green
    from pixelphilly.invented_water import courtyard_lawn

    d = np.zeros((300, 300, 3), np.uint8)
    d[:] = _hsv_rgb(30, 0.10, 0.60)
    b = np.zeros((300, 300), bool)
    b[50:250, 50:250] = True
    b[100:200, 100:200] = False  # enclosed by houses, but no footprint hole
    d[120:180, 120:180] = _hsv_rgb(100, 0.50, 0.50)
    r = np.zeros_like(d); r[:] = _hsv_rgb(30, 0.08, 0.35)
    assert courtyard_lawn(d, r, b, np.zeros((300, 300), bool)) == []


def test_whole_connected_lawn_in_a_courtyard_is_repaired():
    # City Hall: the footprint hole covered only part of the drawn grass
    # (1,105 px flagged of a larger patch). Once a hole confirms the
    # courtyard, the whole connected green patch on open ground goes
    from pixelphilly.invented_water import courtyard_lawn

    d = np.zeros((300, 300, 3), np.uint8)
    d[:] = _hsv_rgb(30, 0.10, 0.60)
    b = np.zeros((300, 300), bool)
    b[50:250, 50:250] = True
    b[80:220, 80:220] = False
    holes = np.zeros((300, 300), bool)
    holes[150:200, 150:200] = True  # smaller than the visible courtyard
    d[90:210, 90:210] = _hsv_rgb(100, 0.50, 0.50)
    d[90:150, 90:150] = _hsv_rgb(110, 0.30, 0.25)  # darker shaded grass, outside the strict band
    r = np.zeros_like(d); r[:] = _hsv_rgb(30, 0.08, 0.35)
    blobs = courtyard_lawn(d, r, b, holes)
    assert len(blobs) == 1 and blobs[0]["area_px"] > 120 * 120 * 0.9
    assert blobs[0]["mask_bbox"].sum() > 120 * 120 * 0.9  # the dark grass too


def test_courtyard_open_to_the_street_leaves_parks_alone():
    # Open ground is one component when the courtyard opens onto the street;
    # a park across the street must keep its green
    from pixelphilly.invented_water import courtyard_lawn

    d = np.zeros((400, 400, 3), np.uint8)
    d[:] = _hsv_rgb(30, 0.10, 0.60)
    b = np.zeros((400, 400), bool)
    b[50:250, 50:250] = True
    b[100:200, 100:200] = False
    b[140:160, 200:250] = False  # a passage to the street
    holes = np.zeros((400, 400), bool); holes[100:200, 100:200] = True
    d[110:190, 110:190] = _hsv_rgb(100, 0.50, 0.50)  # invented grass
    d[300:390, 300:390] = _hsv_rgb(100, 0.50, 0.50)  # a real park across the street
    r = np.zeros_like(d); r[:] = _hsv_rgb(30, 0.08, 0.35)
    blobs = courtyard_lawn(d, r, b, holes)
    assert len(blobs) == 1 and blobs[0]["bbox"][2] <= 250
