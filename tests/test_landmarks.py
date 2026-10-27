"""Landmark windows for the joint sampler (pixelphilly.landmarks)."""

import json

import numpy as np
import pytest

from pixelphilly.landmarks import (
    PROMPT_P1,
    WHERE,
    approved,
    canvas_point,
    center_box,
    frame_at,
    in_center,
    landmark_height,
    landmark_windows,
    plan,
    safety_verdict,
)
from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.windows import WIN, active_grids, two_grids


def _manifest():
    ref = {"local_path": "x.jpg", "license": "CC0", "credit": "c", "source_url": "u"}
    return {"landmarks": [
        {"slug": "a", "name": "A", "lon": -75.16, "lat": 39.95, "status": "ok",
         "references": [{**ref, "pick": "primary"}, {**ref, "pick": "backup"}]},
        {"slug": "b", "name": "B", "lon": -75.16, "lat": 39.95, "status": "excluded",
         "references": [{**ref, "pick": "primary"}]},
        {"slug": "c", "name": "C", "lon": -75.16, "lat": 39.95, "status": "ok",
         "references": [{**ref, "pick": "backup"}]},
        {"slug": "d", "name": "D", "lon": -75.16, "lat": 39.95, "status": "needs_ref", "references": []},
    ]}


def test_only_ok_landmarks_with_one_primary_are_approved():
    got = approved(_manifest())
    assert [g["slug"] for g in got] == ["a"]
    assert got[0]["credit"] == "c"


def test_prompt_names_render_as_picture_2():
    p = PROMPT_P1.format(where=WHERE)
    assert "Redraw Picture 2" in p and "shown in Picture 1" in p


def test_in_center_is_the_middle_three_quarters():
    side = WIN * 8  # 1,024 px
    assert in_center(0, 0, side / 2, side / 2)
    assert in_center(0, 0, side / 8, side / 8)
    assert not in_center(0, 0, side / 8 - 1, side / 2)
    assert not in_center(0, 0, side / 2, 7 * side / 8)  # exclusive upper edge


def test_every_canvas_point_gets_one_window_per_grid_near_its_middle():
    # A 3 x 3 frame canvas
    lh = lw = 3 * 128
    grids = two_grids(lh, lw)
    rng = np.random.default_rng(0)
    for px, py in rng.uniform(0, lw * 8, size=(300, 2)):
        got = landmark_windows({"x": (px, py)}, grids)
        # one per grid (edge windows belong to both grids, so it can be one key)
        assert 1 <= len(got) <= 2 and all(sum(k in g for k in got) >= 1 for g in grids), (px, py)
        edge = min(px, py, lw * 8 - px, lh * 8 - py) < 128
        assert edge or all(in_center(y, x, px, py) for y, x in got), (px, py)


def test_a_window_wanted_by_two_landmarks_goes_to_the_nearer_one():
    grids = [[(0, 0)]]
    c = WIN * 8 / 2
    got = landmark_windows({"near": (c + 10, c), "far": (c + 200, c)}, grids)
    assert got == {(0, 0): "near"}
    # With a second window available, the loser takes it
    got = landmark_windows({"near": (c + 10, c), "far": (c + 200, c)}, [[(0, 0), (0, 48)]])
    assert got == {(0, 0): "near", (0, 48): "far"}


def test_landmark_height_is_the_tallest_part_of_the_nearest_footprint():
    sq = lambda x, y, s: [[[x, y], [x + s, y], [x + s, y + s], [x, y + s]]]  # noqa: E731
    buildings = [
        {"id": "7-0", "h": 36.0, "polys": [sq(0, 0, 10)]},     # the part under the point
        {"id": "7-1", "h": 166.0, "polys": [sq(0, 50, 5)]},    # its tower, 40 m away
        {"id": "9-0", "h": 140.0, "polys": [sq(15, 0, 5)]},    # a neighbor, closer than the tower
        {"id": 12, "h": 20.0, "polys": [sq(100, 100, 10)]},    # an unsplit footprint (int id)
        {"id": "s3-1", "h": 30.0, "polys": [sq(300, 300, 10)]},  # a LiDAR-only structure
    ]
    assert landmark_height(buildings, 5, 5) == 166.0
    assert landmark_height(buildings, 105, 105) == 20.0
    assert landmark_height(buildings, 305, 305) == 30.0
    assert landmark_height(buildings, -200, -200) == 0.0


def test_canvas_point_matches_the_frame_lattice():
    cfg = load_config("atlas_cityhall_lidar")
    frame, cam, frames = area_setup(cfg)
    for f in frames:
        # The ground point seen at a frame's top-left corner lands on that
        # frame's canvas corner
        e, n = cam.screen_to_ground(f.x0 + 0.5, f.y0 + 0.5, 0.0)
        lon, lat = frame.to_wgs84(float(e), float(n))
        px, py = canvas_point(frame, cam, frames, lon, lat, 0.0)
        assert px == pytest.approx(f.col * f.size + 0.5, abs=1e-3)
        assert py == pytest.approx(f.row * f.size + 0.5, abs=1e-3)
        assert frame_at(frames, px, py) is f


def test_lifting_moves_the_point_up_the_screen():
    cfg = load_config("atlas_cityhall_lidar")
    frame, cam, frames = area_setup(cfg)
    x0, y0 = canvas_point(frame, cam, frames, -75.1636, 39.9523, 0.0)
    x1, y1 = canvas_point(frame, cam, frames, -75.1636, 39.9523, 80.0)
    assert x1 == pytest.approx(x0) and y1 < y0
    assert y0 - y1 == pytest.approx(80.0 * np.cos(np.radians(45)) / cfg["camera"]["meters_per_pixel"], rel=1e-6)


def test_center_box_stays_inside_the_frame():
    class F:
        col, row, size = 1, 2, 1024
    assert center_box(1024 + 10, 2048 + 1000, F) == (0, 512, 512, 1024)
    assert center_box(1024 + 512, 2048 + 512, F) == (256, 256, 768, 768)


def test_safety_rule_matches_experiment_a():
    assert safety_verdict((0, 0), (1, -1), 0.17, 0.20) == (True, "ok")
    assert not safety_verdict((-459, -165), (-85, 98), 0.03, 0.20)[0]
    # The art museum photo copy: whole frame read (0, -1); the center caught it
    ok, why = safety_verdict((0, -1), (200, -194), 0.029, 0.224)
    assert not ok and "central" in why
    ok, why = safety_verdict((0, 0), (0, 0), 0.09, 0.20)
    assert not ok and "edge" in why


@pytest.mark.skipif(not (REPO_ROOT / "data/processed/atlas_cityhall_lidar_scene.json").exists()
                    or not (REPO_ROOT / "data/landmarks/manifest.json").exists(), reason="needs local data")
def test_plan_finds_city_hall_in_its_atlas_spot():
    cfg = load_config("atlas_cityhall_lidar")
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    cols, rows = max(f.col for f in frames) + 1, max(f.row for f in frames) + 1
    active = np.zeros((rows * size // 8, cols * size // 8), bool)
    for f in frames:
        active[f.row * size // 8:(f.row + 1) * size // 8, f.col * size // 8:(f.col + 1) * size // 8] = True
    grids = active_grids(two_grids(*active.shape), active)
    keys = {k for g in grids for k in g}
    scene = json.loads((REPO_ROOT / "data/processed/atlas_cityhall_lidar_scene.json").read_text())
    p = plan(cfg, REPO_ROOT / "data/landmarks/manifest.json", scene, grids)
    assert "city_hall" in p["landmarks"]
    ch = p["landmarks"]["city_hall"]
    assert ch["height_m"] > 100  # the tower, not the 30-odd m main block
    assert len(ch["windows"]) == 2 and all(tuple(w) in keys for w in ch["windows"])  # one per grid
    assert set(p["windows"].values()) == set(p["landmarks"])


def _scene_image(seed=0, size=256):
    from PIL import Image, ImageDraw

    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (size, size), (200, 200, 190))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rng.integers(0, size - 40, 2)
        w, h = rng.integers(10, 40, 2)
        d.rectangle((x, y, x + w, y + h), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return im


def test_check_frame_accepts_a_redraw_on_the_render_and_rejects_a_moved_one():
    from PIL import ImageChops

    from pixelphilly.landmarks import check_frame

    render = _scene_image()
    box = (64, 64, 192, 192)
    same = check_frame(render, render, render, box)
    assert same["accepted"] and same["shift_center"] == [0, 0]
    moved = check_frame(render, ImageChops.offset(render, 9, 0), render, box)
    assert not moved["accepted"]
    other = check_frame(render, _scene_image(seed=5), render, box)  # a different picture in the box
    assert not other["accepted"]
