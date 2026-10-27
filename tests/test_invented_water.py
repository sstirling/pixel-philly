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
