import itertools

import numpy as np
import pytest

from pixelphilly.projection import IsoCamera, LocalFrame, frame_lattice, load_config

CFG = load_config("oldcity")
BBOX = CFG["bbox_wgs84"]


@pytest.fixture(scope="module")
def frame():
    return LocalFrame(BBOX)


@pytest.fixture(scope="module")
def cam():
    return IsoCamera.from_config(CFG)


def test_basis_is_orthonormal(cam):
    f, r, u = cam.basis
    for v in (f, r, u):
        assert np.isclose(np.linalg.norm(v), 1.0)
    assert np.isclose(f @ r, 0) and np.isclose(f @ u, 0) and np.isclose(r @ u, 0)
    # The camera looks down, and screen-up has a positive vertical component.
    assert f[2] < 0 and u[2] > 0


def test_wgs84_local_round_trip(frame):
    west, south, east, north = BBOX
    lons = np.linspace(west, east, 7)
    lats = np.linspace(south, north, 7)
    lo, la = np.meshgrid(lons, lats)
    e, n = frame.to_local(lo.ravel(), la.ravel())
    lo2, la2 = frame.to_wgs84(e, n)
    # 1e-9 degrees is about 0.1 mm
    assert np.allclose(lo2, lo.ravel(), atol=1e-9)
    assert np.allclose(la2, la.ravel(), atol=1e-9)


def test_local_distances_match_geodesic(frame):
    # Independence Hall to the Ben Franklin Bridge anchorage is about 600 m;
    # the local frame must agree with the WGS84 geodesic to well under a pixel.
    from pyproj import Geod

    a, b = (-75.1500, 39.9489), (-75.1426, 39.9535)
    _, _, geodesic = Geod(ellps="WGS84").inv(*a, *b)
    (e1, e2), (n1, n2) = frame.to_local([a[0], b[0]], [a[1], b[1]])
    local = np.hypot(e2 - e1, n2 - n1)
    assert abs(local - geodesic) < 0.05


def test_screen_round_trip_under_5cm(frame, cam):
    """lat/lon -> pixel -> lat/lon at several heights."""
    west, south, east, north = BBOX
    rng = np.random.default_rng(0)
    lons = rng.uniform(west, east, 200)
    lats = rng.uniform(south, north, 200)
    for h in (0.0, 12.0, 117.0):
        e, n = frame.to_local(lons, lats)
        sx, sy = cam.world_to_screen(e, n, h)
        e2, n2 = cam.screen_to_ground(sx, sy, h)
        lon2, lat2 = frame.to_wgs84(e2, n2)
        e3, n3 = frame.to_local(lon2, lat2)
        assert np.max(np.hypot(e3 - e, n3 - n)) < 0.05


def test_height_moves_points_straight_up_screen(cam):
    # Standing something up must move it up the screen, not sideways.
    sx0, sy0 = cam.world_to_screen(10.0, 20.0, 0.0)
    sx1, sy1 = cam.world_to_screen(10.0, 20.0, 30.0)
    assert np.isclose(sx0, sx1)
    assert sy1 < sy0


def test_lattice_tiles_without_gaps_or_overlaps(frame, cam):
    size = CFG["camera"]["frame_px"]
    frames = frame_lattice(cam, frame, BBOX, size, max_height_m=120)
    origins = {(f.x0, f.y0) for f in frames}
    assert len(origins) == len(frames), "duplicate frames"
    for f in frames:
        assert f.x0 % size == 0 and f.y0 % size == 0
    xs = sorted({f.x0 for f in frames})
    ys = sorted({f.y0 for f in frames})
    # Full rectangle: every (x, y) combination present, consecutive steps of `size`
    assert origins == set(itertools.product(xs, ys))
    assert all(b - a == size for a, b in zip(xs, xs[1:]))
    assert all(b - a == size for a, b in zip(ys, ys[1:]))


def test_lattice_covers_bbox_corners(frame, cam):
    size = CFG["camera"]["frame_px"]
    frames = frame_lattice(cam, frame, BBOX, size, max_height_m=120)
    x_min = min(f.x0 for f in frames)
    x_max = max(f.x0 for f in frames) + size
    y_min = min(f.y0 for f in frames)
    y_max = max(f.y0 for f in frames) + size
    west, south, east, north = BBOX
    e, n = frame.to_local([west, east, east, west], [south, south, north, north])
    for h in (0.0, 120.0):
        sx, sy = cam.world_to_screen(e, n, h)
        assert sx.min() >= x_min and sx.max() <= x_max
        assert sy.min() >= y_min and sy.max() <= y_max


def test_frustum_matches_screen_convention(cam):
    from pixelphilly.projection import Frame

    f = Frame(col=0, row=0, x0=-1024, y0=2048, size=1024)
    fr = f.frustum(cam.meters_per_pixel)
    assert fr["right"] - fr["left"] == pytest.approx(1024 * cam.meters_per_pixel)
    assert fr["top"] - fr["bottom"] == pytest.approx(1024 * cam.meters_per_pixel)
    # Screen y grows downward, view-space y grows upward
    assert fr["top"] == pytest.approx(-2048 * cam.meters_per_pixel)
