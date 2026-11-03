"""Clipping regions to the city line ("clip_to_city": true).

All on synthetic city polygons written to a temporary file, so the tests
need neither the network nor data/raw/city_limits.geojson."""

import json

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import unary_union

from pixelphilly import projection
from pixelphilly.projection import (
    IsoCamera, LocalFrame, area_screen_polygon, area_setup, frame_lattice, load_config, render_extent_wgs84,
    render_ground_polygon, swept_screen_polygon,
)

CFG = load_config("oldcity")
BBOX = CFG["bbox_wgs84"]
W, S, E, N = BBOX
SIZE = CFG["camera"]["frame_px"]
H = CFG["max_height_m"]


@pytest.fixture
def city(tmp_path, monkeypatch):
    """Write a fake city polygon and point the projection module at it."""

    def write(geom):
        path = tmp_path / "city_limits.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection",
                                    "features": [{"type": "Feature", "properties": {}, "geometry": mapping(geom)}]}))
        monkeypatch.setattr(projection, "CITY_LIMITS", path)
        return path

    return write


def _setup():
    return LocalFrame(BBOX), IsoCamera.from_config(CFG)


def _cells(frames):
    return {(f.col, f.row, f.x0, f.y0) for f in frames}


def test_swept_bbox_equals_the_area_polygon():
    frame, cam = _setup()
    swept = swept_screen_polygon(cam, frame, box(*BBOX), H)
    area = area_screen_polygon(cam, frame, BBOX, H)
    assert swept.symmetric_difference(area).area < 1e-6 * area.area


def test_whole_bbox_as_ground_keeps_the_clipped_lattice():
    frame, cam = _setup()
    clipped = frame_lattice(cam, frame, BBOX, SIZE, H, clip=True)
    ground = frame_lattice(cam, frame, BBOX, SIZE, H, ground=box(*BBOX))
    assert _cells(ground) == _cells(clipped)


def test_triangle_ground_keeps_exactly_the_frames_that_see_it():
    frame, cam = _setup()
    tri = Polygon([(W, S), (E, S), (W, N)])  # the bbox's south-west half
    full = frame_lattice(cam, frame, BBOX, SIZE, H)
    kept = frame_lattice(cam, frame, BBOX, SIZE, H, ground=tri)
    swept = swept_screen_polygon(cam, frame, tri, H)
    assert 0 < len(kept) < len(frame_lattice(cam, frame, BBOX, SIZE, H, clip=True))
    # Same lattice indices as the full rectangle, so mosaics still line up
    assert _cells(kept) <= _cells(full)
    names = {f.name for f in kept}
    for f in full:
        hit = box(f.x0, f.y0, f.x0 + SIZE, f.y0 + SIZE).intersects(swept)
        assert hit == (f.name in names)
    covered = unary_union([box(f.x0, f.y0, f.x0 + SIZE, f.y0 + SIZE) for f in kept])
    assert covered.contains(swept)


def test_swept_polygon_reaches_up_to_max_height():
    # A tall building standing on the ground polygon's top edge must still
    # land inside: the swept footprint includes the ground lifted to H
    frame, cam = _setup()
    tri = Polygon([(W, S), (E, S), (W, N)])
    swept = swept_screen_polygon(cam, frame, tri, H)
    e, n = frame.to_local([W, (W + E) / 2], [N, (S + N) / 2])
    for h in (0.0, H / 2, H):
        sx, sy = cam.world_to_screen(e, n, h)
        for x, y in zip(sx, sy):
            assert swept.buffer(1e-6).contains(Point(float(x), float(y)))


def test_multipolygon_ground():
    frame, cam = _setup()
    dx, dy = (E - W) / 6, (N - S) / 6
    two = MultiPolygon([box(W, S, W + dx, S + dy), box(E - dx, N - dy, E, N)])
    kept = frame_lattice(cam, frame, BBOX, SIZE, H, ground=two)
    each = (_cells(frame_lattice(cam, frame, BBOX, SIZE, H, ground=g)) for g in two.geoms)
    assert _cells(kept) == set().union(*each)


def test_clip_to_city_uses_bbox_intersect_city(city):
    # The city covers only the western 40% of the bbox
    city(box(W - 0.05, S - 0.05, W + 0.4 * (E - W), N + 0.05))
    cfg = {**CFG, "clip_to_city": True}
    _, _, frames = area_setup(cfg)
    _, _, full = area_setup(CFG)
    assert 0 < len(frames) < len(full)
    assert _cells(frames) <= _cells(full)
    frame, cam = _setup()
    expect = frame_lattice(cam, frame, BBOX, SIZE, H, ground=box(W, S, W + 0.4 * (E - W), N))
    assert _cells(frames) == _cells(expect)


def test_city_covering_the_bbox_equals_plain_clipping(city):
    city(box(W - 1, S - 1, E + 1, N + 1))
    clipped = area_setup({**CFG, "clip_frames_to_area": True})[2]
    assert _cells(area_setup({**CFG, "clip_to_city": True})[2]) == _cells(clipped)


def test_ground_polygon_and_extent_follow_the_kept_frames(city):
    city(box(W - 0.05, S - 0.05, W + 0.4 * (E - W), N + 0.05))
    cfg = {**CFG, "clip_to_city": True}
    ground = render_ground_polygon(cfg)
    plain = render_ground_polygon({**CFG, "clip_frames_to_area": True})
    assert ground.area < plain.area
    # (the 50 m margins are polygonized arcs, so compare areas, not contains)
    assert ground.difference(plain).area < 1e-6 * ground.area
    # Everything inside bbox and city is seen
    assert ground.contains(box(W, S, W + 0.4 * (E - W), N))
    # clip_to_city alone switches the fetch extent to the kept frames' ground
    assert render_extent_wgs84(cfg) == list(ground.bounds)
    assert projection.is_clipped(cfg) and not projection.is_clipped(CFG)


def test_bbox_outside_the_city_is_an_error(city):
    city(box(W - 1, S - 1, W - 0.5, S - 0.5))
    with pytest.raises(ValueError, match="city"):
        area_setup({**CFG, "clip_to_city": True})


def test_missing_city_file_says_how_to_fetch_it(tmp_path, monkeypatch):
    monkeypatch.setattr(projection, "CITY_LIMITS", tmp_path / "nope.geojson")
    with pytest.raises(FileNotFoundError, match="04l_fetch_city_limits"):
        area_setup({**CFG, "clip_to_city": True})


def test_city_file_is_reread_when_it_changes(city):
    import os

    p = city(box(W - 1, S - 1, E + 1, N + 1))
    a = projection.city_polygon()
    city(box(W, S, W + 0.001, S + 0.001))
    os.utime(p, ns=(p.stat().st_mtime_ns + 10**9, p.stat().st_mtime_ns + 10**9))
    assert projection.city_polygon().area < a.area


@pytest.mark.parametrize("name,count", [("south_lidar", 672), ("north_lidar", 239),
                                        ("upper_north_lidar", 235), ("west_lidar", 158)])
def test_existing_regions_unchanged(name, count):
    cfg = load_config(name)
    assert "clip_to_city" not in cfg
    assert len(area_setup(cfg)[2]) == count


def test_outline_coords_handles_split_render_tiles():
    # With clipping, a render tile's kept frames can be two separate pieces
    # (southwest's first build crashed on reach.exterior, Nov. 2)
    from pixelphilly.projection import outline_coords

    one = box(0, 0, 2, 1)
    assert outline_coords(one).tolist() == [list(c) for c in one.exterior.coords]
    two = MultiPolygon([box(0, 0, 1, 1), box(3, 2, 4, 3)])
    c = outline_coords(two)
    assert c[:, 0].min() == 0 and c[:, 0].max() == 4 and c[:, 1].min() == 0 and c[:, 1].max() == 3
