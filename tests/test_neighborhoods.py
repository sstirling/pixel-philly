"""Neighborhood print images: boundary loading and area (src/pixelphilly/neighborhoods.py),
the building and tree assignment rules of the cut-out mask, and the layout of the
print, desktop and phone images (scripts/41_neighborhood_prints.py).

Everything here is synthetic and small: a hand-made GeoJSON, a 64 x 64 px
"canvas" of 16 px tiles with a drawn building or tree, and tiny pyvips images.
Nothing reads the map tiles."""

import importlib.util
import json

import numpy as np
import pytest

from pixelphilly import neighborhoods as nb
from pixelphilly.projection import REPO_ROOT

_spec = importlib.util.spec_from_file_location("neighborhood_prints", REPO_ROOT / "scripts" / "41_neighborhood_prints.py")
prints = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prints)

# One square, 0.01 degree on a side, at the equator: on the WGS84 ellipsoid
# 1,113.19 m (longitude) x 1,105.74 m (latitude) = 1.23091 km2 = 0.475255 sq mi
EQ_SQUARE = [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]
EQ_SQUARE_SQMI = 0.475255
HOLE = [[0.0025, 0.0025], [0.0025, 0.0075], [0.0075, 0.0075], [0.0075, 0.0025], [0.0025, 0.0025]]  # a quarter of the area


def _shift(ring, dlon):
    return [[x + dlon, y] for x, y in ring]


def _write_geojson(tmp_path, features):
    path = tmp_path / "hoods.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAME": n.upper(), "LISTNAME": n, "MAPNAME": n, "Shape_Area": None},
         "geometry": {"type": "MultiPolygon", "coordinates": c}} for n, c in features]}))
    return path


def test_load_multipolygon_with_hole_and_area(tmp_path):
    path = _write_geojson(tmp_path, [
        ("Square", [[EQ_SQUARE]]),
        # Two squares, the first with a hole: 1 - 1/4 + 1 = 1.75 squares
        ("Two Parts - With Hole", [[EQ_SQUARE, HOLE], [_shift(EQ_SQUARE, 0.02)]]),
        ("Square", [[_shift(EQ_SQUARE, 0.05)]]),  # same name, needs its own slug
    ])
    hoods = nb.load_neighborhoods(path)
    assert [h["name"] for h in hoods] == ["Square", "Two Parts - With Hole", "Square"]
    assert [h["slug"] for h in hoods] == ["square", "two-parts-with-hole", "square-2"]
    assert hoods[0]["sqmi"] == pytest.approx(EQ_SQUARE_SQMI, rel=2e-3)
    assert hoods[1]["sqmi"] == pytest.approx(1.75 * EQ_SQUARE_SQMI, rel=2e-3)
    assert len(hoods[1]["polygons_lonlat"]) == 2 and len(hoods[1]["polygons_lonlat"][0]) == 2


def test_slug_is_ascii():
    assert nb.slugify("Fishtown - Lower Kensington") == "fishtown-lower-kensington"
    assert nb.slugify("Cedar Park / Spruce Hill's Édge") == "cedar-park-spruce-hill-s-edge"


def test_rasterize_hole_and_multipolygon():
    # Checked points stay a pixel or more off every edge: PIL's edge rule is
    # only exact to a pixel
    outer = [(2, 2), (30, 2), (30, 30), (2, 30)]
    hole = [(8, 8), (24, 8), (24, 24), (8, 24)]
    island = [(14, 14), (18, 14), (18, 18), (14, 18)]  # a second polygon inside the first one's hole
    g = nb.rasterize_polygons([[outer, hole], [island]], 0, 0, 32, 32)
    assert g[4, 4] and g[28, 28] and not g[0, 0] and not g[31, 31]
    assert not g[10, 10] and not g[21, 21]  # in the hole
    assert g[16, 16]  # on the island
    # The window offset: the same shape seen from (16, 16)
    assert nb.rasterize_polygons([[outer, hole], [island]], 16, 16, 16, 16)[0, 0]


# A synthetic map: 64 x 64 px in 16 px tiles. The neighborhood is the band
# 24 <= y < 40 (map px), full width. Its region therefore spans tile rows 0-3.
T, W, H = 16, 64, 64
BAND = [[[(0, 24), (64, 24), (64, 40), (0, 40)]]]


def _readers(buildings, trees):
    def tile(arr, tx, ty):
        t = arr[ty * T:(ty + 1) * T, tx * T:(tx + 1) * T]
        return t.copy() if t.any() else None
    return (lambda tx, ty: tile(buildings, tx, ty)), (lambda tx, ty: tile(trees, tx, ty))


def _mask(buildings, trees):
    rb, rt = _readers(buildings, trees)
    m = nb.neighborhood_mask(BAND, rb, rt, W, H, tile=T, up=20, pad=2, strip_tiles=2)
    full = np.zeros((H, W), bool)
    x0, y0 = m["origin"]
    h, w = m["mask"].shape
    full[y0:y0 + h, x0:x0 + w] = m["mask"]
    return full


def test_building_with_base_inside_is_kept_whole():
    b = np.zeros((H, W), bool)
    b[10:36, 20:26] = True  # base at y = 35, inside the band; rises 14 px above it
    full = _mask(b, np.zeros((H, W), np.uint8))
    assert full[10:36, 20:26].all()  # the whole tower, roof included
    assert full[24:40, 0:20].all()  # plain ground in the band
    assert not full[10:23, 0:20].any()  # plain ground above the band


def test_tower_from_outside_is_excluded():
    b = np.zeros((H, W), bool)
    b[28:46, 40:46] = True  # base at y = 45, south of the band; its top rises into it
    full = _mask(b, np.zeros((H, W), np.uint8))
    assert not full[28:46, 40:46].any()
    assert full[28:40, 39].all() and full[28:40, 46].all()  # the ground beside it stays


def test_tree_is_assigned_by_its_trunk():
    t = np.zeros((H, W), np.uint8)
    # Crown A: rows 30-33 at x 4-7, trunk at y = 33 + 8 = 41 (outside: the band ends at 39)
    for y in range(30, 34):
        t[y, 4:8] = 41 - y
    # Crown B: rows 16-21 at x 50-53, trunk at y = 21 + 4 = 25 (inside), crown above the band
    for y in range(16, 22):
        t[y, 50:54] = 25 - y
    full = _mask(np.zeros((H, W), bool), t)
    assert not full[30:34, 4:8].any()
    assert full[16:22, 50:54].all()


def test_tall_building_cut_by_region_top_is_reported():
    b = np.zeros((H, W), bool)
    b[0:36, 20:26] = True  # rises past the region's top (band top 24 - up 20 = 4)
    rb, rt = _readers(b, np.zeros((H, W), np.uint8))
    m = nb.neighborhood_mask(BAND, rb, rt, W, H, tile=T, up=20, pad=2, strip_tiles=2)
    assert m["touches_top"]


def test_text_is_inside_the_frame_and_in_the_margin():
    for size in [(5120, 2880), (1290, 2796), (900, 700)]:
        margin = prints.margin_px(*size)
        boxes = prints.label_boxes(size, "Fishtown - Lower Kensington", prints.URL)
        for x0, y0, x1, y1 in boxes:
            assert 0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]
        assert boxes[0][1] < boxes[1][1]  # the name above the URL
        assert min(b[1] for b in boxes) >= size[1] - margin  # inside the bottom margin
        assert boxes[0][3] - boxes[0][1] < 0.04 * min(size)  # small


@pytest.mark.parametrize("target", [prints.DESKTOP, prints.PHONE])
def test_desktop_and_phone_have_exact_sizes(target):
    import pyvips
    for w, h in [(400, 300), (300, 1000), (1001, 999)]:
        art = pyvips.Image.black(w, h, bands=3) + 128
        out = prints.fit_canvas(art.cast("uchar"), *target)
        out = prints.draw_label(out, "Chestnut Hill", prints.URL)
        assert (out.width, out.height, out.bands) == (*target, 3)
        # The backdrop shows in the corners, the art in the middle
        assert out.getpoint(2, 2) == list(prints.BACKDROP_RGB)
        assert out.getpoint(target[0] // 2, target[1] // 2) == [128, 128, 128]


def test_scene_buildings_decide_merged_runs():
    """A tower inside stands behind a lower building outside, so on screen the
    front building's roof meets the tower's wall and the column runs merge.
    The column rule alone drops both (the merged run's bottom is outside);
    with the scene buildings the tower is kept and the front building dropped."""
    b = np.zeros((H, W), bool)
    b[10:37, 20:26] = True  # tower: footprint rows 30-36 (inside), 20 px tall
    b[33:48, 18:28] = True  # front building: footprint rows 41-47 (outside), 7 px tall
    tower = nb.Prism([np.array([(20, 30), (26, 30), (26, 37), (20, 37), (20, 30)], float)], 20.0, 23, 33.5)
    front = nb.Prism([np.array([(18, 41), (28, 41), (28, 48), (18, 48), (18, 41)], float)], 8.0, 23, 44.5)
    rb, rt = _readers(b, np.zeros((H, W), np.uint8))
    plain = nb.neighborhood_mask(BAND, rb, rt, W, H, tile=T, up=20, pad=2, strip_tiles=2)
    assert not plain["mask"][10 - plain["origin"][1], 22]  # the column rule loses the tower
    m = nb.neighborhood_mask(BAND, rb, rt, W, H, tile=T, up=20, pad=2, strip_tiles=2, prisms=[front, tower])
    full = np.zeros((H, W), bool)
    x0, y0 = m["origin"]
    full[y0:y0 + m["mask"].shape[0], x0:x0 + m["mask"].shape[1]] = m["mask"]
    assert full[10:33, 20:26].all()  # the tower, up to where the front building covers it
    assert not full[33:40, 18:28].any()  # the front building, though drawn over the band


def test_tree_vote_smooths_column_stripes():
    """One crown on the line whose per-column trunks alternate inside and
    outside (as overlapping crowns do) is decided as a whole, not in stripes."""
    t = np.zeros((H, W), np.uint8)
    for x in range(30, 42):
        trunk = 38 if x % 4 else 42  # one column in four reads outside
        for y in range(28, 34):
            t[y, x] = trunk - y
    full = _mask(np.zeros((H, W), bool), t)
    assert full[28:34, 30:42].all()


# Phone wallpaper: a screen-filling crop, not the whole shape on a backdrop (Stephen,
# Nov. 19: wide neighborhoods came out small on a tall phone screen)

def test_phone_crop_fills_the_screen_inside_a_wide_neighborhood():
    # A wide neighborhood: 20,000 x 6,000 px, center of mass right of the middle
    x0, y0, x1, y1 = prints.phone_rect((1000, 2000, 21000, 8000), (15000, 5000), (82944, 89088))
    assert (x1 - x0) / (y1 - y0) == pytest.approx(1290 / 2796, abs=0.002)
    assert y1 - y0 == 6000  # as tall as the neighborhood
    assert (x0 + x1) / 2 == pytest.approx(15000, abs=1)  # centered on its center of mass
    assert y0 == 2000


def test_phone_crop_stays_inside_the_neighborhood_and_the_map():
    # Center of mass near the right edge: the crop slides back inside the bounds
    x0, y0, x1, y1 = prints.phone_rect((1000, 2000, 21000, 8000), (20900, 5000), (82944, 89088))
    assert x1 == 21000
    # A tiny neighborhood: never smaller than the phone screen (no upscaling),
    # still inside the map canvas
    x0, y0, x1, y1 = prints.phone_rect((100, 80000, 900, 80600), (500, 80300), (82944, 89088))
    assert (x1 - x0, y1 - y0) == (1290, 2796)
    assert x0 >= 0 and y1 <= 89088
