"""Scene options for the suspension bridges (Ben Franklin, Walt Whitman):
raised prisms ("z0"), flat-colored tops ("roof_rgb") and tubes (cables and
hangers). Covers the scene writer (scripts/05_build_scene.py), the alignment
check (scripts/09_check_alignment.py) and a headless render of
render/render.js."""

import importlib.util
import json
import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import box

from pixelphilly.projection import REPO_ROOT, IsoCamera, load_config


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_scene = _load("build_scene", "05_build_scene.py")
align = _load("align", "09_check_alignment.py")

RING = [[-15.0, -10.0], [15.0, -10.0], [15.0, 10.0], [-15.0, 10.0]]


def _part(**extra):
    # fixed_color skips the aerial sampling, so no ground mosaic is needed
    return {"id": "deck", "h": 48.0, "polys": [[RING]], "fixed_color": [86, 120, 156], **extra}


# --- scene writer ------------------------------------------------------------

def test_colored_passes_z0_and_roof_rgb_through():
    (out,) = build_scene.colored([_part(z0=40.0, roof_rgb=(70, 70, 72))], ground=None, cfg={})
    assert out["z0"] == 40.0
    assert out["roof_rgb"] == [70, 70, 72]
    assert out["h"] == 48.0 and out["color"] == [86, 120, 156]


def test_colored_omits_bridge_keys_when_not_set():
    # Existing scenes must stay byte-identical: no new keys, same key order
    (out,) = build_scene.colored([_part()], ground=None, cfg={})
    assert list(out) == ["id", "h", "color", "polys"]
    (out,) = build_scene.colored([_part(z0=0.0, roof_rgb=None)], ground=None, cfg={})
    assert list(out) == ["id", "h", "color", "polys"]


def _tube(tid, pts, r=0.75):
    return {"id": tid, "pts": pts, "r": r, "color": [120, 120, 125]}


def test_tubes_go_to_tiles_whose_reach_they_meet():
    reach = box(0, 0, 100, 100)
    inside = _tube("in", [[50, 50, 0], [50, 50, 60]])
    crossing = _tube("cross", [[-500, 50, 100], [-200, 50, 50], [150, 50, 100]])  # only the bbox meets it
    near = _tube("edge", [[100.5, 50, 0], [100.5, 50, 60]])  # 0.5 m out, but its radius reaches in
    outside = _tube("out", [[300, 300, 0], [300, 300, 60]])
    got = build_scene.tubes_in_reach([inside, crossing, near, outside], reach)
    assert [t["id"] for t in got] == ["in", "cross", "edge"]
    assert build_scene.tubes_in_reach([], reach) == []


def _scene_dict(tubes):
    cfg = {"name": "t", "camera": {"frame_px": 64}}
    cam = IsoCamera(54.0, 45.0, 0.293)
    frame = SimpleNamespace(lon0=-75.1, lat0=39.9)
    ground = {"uv": ([0] * 6, [0] * 6), "extent_m": [0, 0, 1, 1]}
    return build_scene.scene_dict(cfg, frame, cam, [], ground, "g.jpg", [], [], tubes)


def test_scene_has_tubes_key_only_when_there_are_tubes():
    assert "tubes" not in _scene_dict(None)
    assert "tubes" not in _scene_dict([])
    t = _tube("cable", [[0, 0, 100], [50, 0, 50], [100, 0, 100]])
    assert _scene_dict([t])["tubes"] == [t]


# --- alignment check ---------------------------------------------------------

def test_alignment_silhouette_starts_at_z0():
    cam = IsoCamera(54.0, 45.0, 0.293)
    (raised,) = align.silhouettes([{"h": 48.0, "z0": 40.0, "polys": [[RING]]}], cam)
    (full,) = align.silhouettes([{"h": 48.0, "polys": [[RING]]}], cam)
    r = np.array(RING)
    sx, sy = cam.world_to_screen(np.r_[r[:, 0], r[:, 0]], np.r_[r[:, 1], r[:, 1]], np.r_[[40.0] * 4, [48.0] * 4])
    x0, y0, x1, y1 = raised.bounds
    assert np.allclose([x0, y0, x1, y1], [sx.min(), sy.min(), sx.max(), sy.max()], atol=1e-6)
    # A ground-based prism of the same height reaches 40 m further down-screen
    assert full.bounds[3] - y1 == pytest.approx(40.0 * np.cos(np.radians(45.0)) / 0.293, rel=1e-6)


# --- headless render ---------------------------------------------------------

SIZE = 256
GRAY = (128, 128, 128)


@pytest.fixture(scope="module")
def render_root():
    """Scenes on a flat gray aerial, written under output/_test_render_features
    (the renderer serves the repo): a raised deck with a flat top, and a sagging
    cable plus a vertical hanger."""
    root = REPO_ROOT / "output" / "_test_render_features"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    Image.new("RGB", (64, 64), GRAY).save(root / "ground.png")
    cfg = load_config("south_lidar")
    cam = IsoCamera.from_config(cfg)
    mpp = cam.meters_per_pixel
    sx, sy = cam.world_to_screen(0.0, 0.0, 44.0)
    half = SIZE / 2
    x0, y0 = float(sx) - half, float(sy) - half
    frame = {"name": "f", "col": 0, "row": 0, "left": x0 * mpp, "right": (x0 + SIZE) * mpp,
             "top": -y0 * mpp, "bottom": -(y0 + SIZE) * mpp}
    scene = {"name": "t", "camera": cam.three_js_params(3000.0), "meters_per_pixel": mpp, "frame_px": SIZE,
             "frames": [frame], "trees": [],
             "ground": {"image": "output/_test_render_features/ground.png", "extent_m": [-200, -200, 200, 200],
                        "uv_poly": {"u": [0.0025, 0, 0.5, 0, 0, 0], "v": [0, 0.0025, 0.5, 0, 0, 0]}}}
    deck = {"id": "deck", "h": 48.0, "z0": 40.0, "color": [86, 120, 156], "roof_rgb": [70, 70, 72],
            "polys": [[RING]]}
    cable = {"id": "cable", "r": 0.75, "color": [200, 60, 50],
             "pts": [[-25, -60, 70], [-25, -30, 55], [-25, 0, 50], [-25, 30, 55], [-25, 60, 70]]}
    hanger = {"id": "hanger", "r": 0.3, "color": [200, 60, 50], "pts": [[-25, 30, 0], [-25, 30, 55]]}
    (root / "deck.json").write_text(json.dumps({**scene, "buildings": [deck]}))
    (root / "tubes.json").write_text(json.dumps({**scene, "buildings": [], "tubes": [cable, hanger]}))
    yield SimpleNamespace(root=root, cam=cam, x0=x0, y0=y0, deck=deck, tubes=[cable, hanger])
    shutil.rmtree(root, ignore_errors=True)


def _render(rel, mode="color"):
    from pixelphilly.browser_render import Renderer

    with Renderer(f"output/_test_render_features/{rel}", SIZE) as r:
        return np.asarray(r.frame(0, mode)).astype(int)


def test_raised_deck_matches_projection_with_flat_top(render_root):
    t = render_root
    mask = _render("deck.json", "mask")[..., 0] > 127
    expected = align.rasterize(align.silhouettes([t.deck], t.cam), {"x0": t.x0, "y0": t.y0}, SIZE)
    assert expected.sum() > 1000
    assert align.tolerant_iou(mask, expected) > 0.99
    ys, xs = np.nonzero(mask)
    ye, xe = np.nonzero(expected)
    for a, b in ((xs.min(), xe.min()), (xs.max(), xe.max()), (ys.min(), ye.min()), (ys.max(), ye.max())):
        assert abs(int(a) - int(b)) <= 1
    # The top is exactly roof_rgb, not the gray aerial
    color = _render("deck.json")
    r = np.array(RING)
    sx, sy = t.cam.world_to_screen(r[:, 0], r[:, 1], 48.0)
    top = Image.new("L", (SIZE, SIZE))
    ImageDraw.Draw(top).polygon([(x - t.x0, y - t.y0) for x, y in zip(sx, sy)], fill=255)
    inner = np.asarray(top.filter(ImageFilter.MinFilter(5))) > 0
    assert inner.sum() > 300
    assert (color[inner] == [70, 70, 72]).all()


def test_tubes_render_lit_and_white_in_mask(render_root):
    t = render_root
    mask = _render("tubes.json", "mask")[..., 0] > 127
    color = _render("tubes.json")
    # Inner curve points (the curve passes through them) and a hanger's
    # midpoint land on the mask. Tube ends are open, so an end seen at a
    # slant can be a hollow ring and is not tested
    for tube in t.tubes:
        p = np.array(tube["pts"], float)
        for e, n, z in (p[1:-1] if len(p) > 2 else [p.mean(axis=0)]):
            sx, sy = t.cam.world_to_screen(e, n, z)
            px, py = int(float(sx) - t.x0), int(float(sy) - t.y0)
            if 1 <= px < SIZE - 1 and 1 <= py < SIZE - 1:
                assert mask[py - 1:py + 2, px - 1:px + 2].any(), (tube["id"], e, n, z)
    # Lit like walls: shaded reds, not one flat color
    red = mask & (color[..., 0] > color[..., 1] + 40)
    assert red.sum() > 0.8 * mask.sum() > 100
    assert len(np.unique(color[red], axis=0)) > 5
