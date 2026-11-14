"""scripts/29_flyover.py camera paths: holds, pans, zooms, cuts and captions.

A stub pyramid stands in for the tiles: camera_path only needs the map size and
a lon/lat -> pixel conversion."""

import importlib.util
import json

import pytest

from pixelphilly.projection import REPO_ROOT

_spec = importlib.util.spec_from_file_location("flyover", REPO_ROOT / "scripts" / "29_flyover.py")
fly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fly)


class StubPyramid:
    w, h = 10_000, 8_000

    def to_px(self, lon, lat, z=0.0):
        # Any fixed mapping will do; z shifts up as a height does on the map
        return lon * 100.0, lat * 100.0 - z


def path(shots, start=None, fps=10):
    cfg = {"size": [100, 50], "fps": fps, "start": start or {"lonlat": [10, 20], "scale": 1.0}, "shots": shots}
    return list(fly.camera_path(cfg, StubPyramid()))


def test_hold_keeps_the_view():
    frames = path([{"seconds": 1, "hold": True}])
    assert len(frames) == 10
    assert all(f["view"] == (1000.0, 2000.0, 1.0) for f in frames)
    assert all(f["prev"] is None for f in frames)


def test_pan_ends_on_target():
    frames = path([{"seconds": 2, "lonlat": [12, 20]}])
    assert len(frames) == 20
    assert frames[-1]["view"] == pytest.approx((1200.0, 2000.0, 1.0))


def test_pan_by_pixel_offset():
    frames = path([{"seconds": 1, "by": [300, -40]}])
    assert frames[-1]["view"] == pytest.approx((1300.0, 1960.0, 1.0))


def test_cut_crossfades_from_old_view_to_new_view():
    frames = path([{"seconds": 1, "cut": True, "lonlat": [50, 60], "z": 10, "scale": 2.0}])
    assert len(frames) == 10
    for f in frames:
        assert f["prev"]["view"] == (1000.0, 2000.0, 1.0)  # the old view stays still
        assert f["view"] == (5000.0, 5990.0, 2.0)          # the new view is already in place
    alphas = [f["alpha"] for f in frames]
    assert alphas == sorted(alphas) and alphas[-1] == 1.0 and alphas[0] > 0


def test_offset_nudges_a_point_target():
    # "offset" (map px) aims a scene off its lon/lat, e.g. onto a bridge deck
    frames = path([{"seconds": 0.5, "cut": True, "lonlat": [50, 60], "offset": [-200, -300]}],
                  start={"lonlat": [10, 20], "scale": 1.0, "offset": [5, 5]})
    assert frames[0]["prev"]["view"] == (1005.0, 2005.0, 1.0)
    assert frames[-1]["view"] == (4800.0, 5700.0, 1.0)


def test_after_a_cut_the_next_pan_starts_from_the_new_view():
    frames = path([{"seconds": 0.5, "cut": True, "lonlat": [50, 60]}, {"seconds": 1, "by": [100, 0]}])
    assert frames[-1]["view"] == pytest.approx((5100.0, 6000.0, 1.0))
    assert frames[-1]["prev"] is None


def test_captions_follow_the_scene():
    frames = path([
        {"seconds": 1, "hold": True},
        {"seconds": 0.5, "cut": True, "lonlat": [50, 60], "caption": "Bridge"},
        {"seconds": 1, "by": [10, 0]},
        {"seconds": 1, "fit": True, "caption": "The whole city"},
    ], start={"lonlat": [10, 20], "scale": 1.0, "caption": "Title"})
    assert frames[0]["caption"] == "Title"
    fade = frames[10]
    assert fade["caption"] == "Bridge" and fade["prev"]["caption"] == "Title"
    assert frames[20]["caption"] == "Bridge"
    assert frames[-1]["caption"] == "The whole city"


def test_cut_back_to_start_closes_a_loop():
    # A GIF loops cleanly when the last frame is the first frame's view
    start = {"lonlat": [10, 20], "scale": 1.0}
    frames = path([{"seconds": 1, "by": [200, 0]}, {"seconds": 0.5, "cut": True, "lonlat": [10, 20]}], start=start)
    assert frames[-1]["view"] == (1000.0, 2000.0, 1.0) and frames[-1]["alpha"] == 1.0


def test_preview_path_is_unchanged():
    # The Nov. 5 preview video had 885 frames; the camera rewrite must not move it
    cfg = json.loads((REPO_ROOT / "config" / "flyover" / "preview.json").read_text())
    frames = list(fly.camera_path(cfg, StubPyramid()))
    assert len(frames) == 885
    assert all(f["prev"] is None for f in frames)


def test_parse_size():
    assert fly.parse_size("1080x1920") == (1080, 1920)
    with pytest.raises(ValueError):
        fly.parse_size("1080")


def test_safe_area_layout_keeps_all_text_inside_the_safe_box():
    # TikTok/Reels cover the top, bottom and right edge with their own UI; every
    # label, caption and credit must land inside the safe box
    from PIL import Image
    import numpy as np

    W, H = 1080, 1920
    safe = {"top": 270, "right": 150, "bottom": 672, "left": 65}
    img = Image.new("RGB", (W, H), (128, 128, 128))
    fly.draw_overlays(img, caption="South Philadelphia sports complex", label="pixelphilly.sstirling.com",
                      credit="AI-generated illustration. Data: City of Philadelphia, USGS, © OpenStreetMap contributors",
                      safe=safe)
    changed = np.argwhere((np.asarray(img) != 128).any(axis=2))
    assert len(changed) > 0
    ys, xs = changed[:, 0], changed[:, 1]
    assert ys.min() >= safe["top"] and ys.max() < H - safe["bottom"]
    assert xs.min() >= safe["left"] and xs.max() < W - safe["right"]


def test_label_and_caption_do_not_overlap():
    from PIL import Image
    import numpy as np

    W, H = 1080, 1920
    safe = {"top": 270, "right": 150, "bottom": 672, "left": 65}
    a = Image.new("RGB", (W, H), (128, 128, 128))
    fly.draw_overlays(a, caption=None, label="pixelphilly.sstirling.com", credit="", safe=safe)
    b = Image.new("RGB", (W, H), (128, 128, 128))
    fly.draw_overlays(b, caption="Center City", label=None, credit="", safe=safe)
    ma = (np.asarray(a) != 128).any(axis=2)
    mb = (np.asarray(b) != 128).any(axis=2)
    assert ma.any() and mb.any() and not (ma & mb).any()


def _via_frames():
    import math
    # Start at (1000, 2000); sweep through (3000, 2000) to (3000, 4000)
    return path([{"seconds": 10, "ramp": 0.25, "via": [
        {"lonlat": [30, 20], "caption": "Middle"},
        {"lonlat": [30, 40], "caption": "End"},
    ]}], start={"lonlat": [10, 20], "scale": 1.0, "caption": "Start"})


def test_via_sweep_passes_through_every_waypoint_and_ends_on_the_last():
    import math
    frames = _via_frames()
    assert len(frames) == 100
    assert frames[-1]["view"] == pytest.approx((3000.0, 4000.0, 1.0))
    closest = min(math.dist(f["view"][:2], (3000, 2000)) for f in frames)
    assert closest < 30  # a frame lands right on the middle waypoint (within one frame's travel)


def test_via_sweep_never_stops_between_waypoints():
    import math
    frames = _via_frames()
    steps = [math.dist(a["view"][:2], b["view"][:2]) for a, b in zip(frames, frames[1:])]
    cruise = steps[30:70]  # past the 25% ramp at each end
    assert min(cruise) > 0.8 * max(cruise)  # steady speed through the middle waypoint
    assert max(steps) < 1.35 * (sum(steps) / len(steps))  # peak is 1 / (1 - ramp) = 1.33x the average


def test_via_sweep_captions_switch_between_waypoints():
    frames = _via_frames()
    caps = [f["caption"] for f in frames]
    assert caps[0] == "Start" and caps[-1] == "End"
    assert "Middle" in caps
    # Each caption appears once, in order
    order = [c for i, c in enumerate(caps) if i == 0 or caps[i - 1] != c]
    assert order == ["Start", "Middle", "End"]
