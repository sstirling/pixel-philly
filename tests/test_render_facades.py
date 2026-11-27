"""Headless smoke test of the procedural façade shader (render/render.js)."""

import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageFilter

from pixelphilly.browser_render import Renderer
from pixelphilly.facades import compact, facade_spec
from pixelphilly.projection import REPO_ROOT, IsoCamera, load_config

SIZE = 256
GRAY = (128, 128, 128)


@pytest.fixture(scope="module")
def scenes():
    """Two scenes of one 20 x 20 x 30 m building on a flat gray aerial:
    with and without a façade. Written under output/_test_render (the
    renderer serves the repo)."""
    from shapely.geometry import box

    root = REPO_ROOT / "output" / "_test_render"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    Image.new("RGB", (64, 64), GRAY).save(root / "ground.png")
    cfg = load_config("oldcity")
    cam = IsoCamera.from_config(cfg)
    sx, sy = cam.world_to_screen(np.array([0.0]), np.array([0.0]), 15.0)
    mpp = cfg["camera"]["meters_per_pixel"]
    half = SIZE / 2
    frame = {"name": "f", "col": 0, "row": 0,
             "left": (float(sx[0]) - half) * mpp, "right": (float(sx[0]) + half) * mpp,
             "top": -(float(sy[0]) - half) * mpp, "bottom": -(float(sy[0]) + half) * mpp}
    base = json.loads((REPO_ROOT / "data" / "processed" / "oldcity_scene.json").read_text())
    ring = [[-10, -10], [10, -10], [10, 10], [-10, 10]]
    building = {"id": 1, "h": 30.0, "color": [150, 140, 130], "polys": [[ring]]}
    spec = facade_spec({"building_code_description": "APT 2-4 UNITS 5 STY MASON",
                        "building_code_description_new": "ROW MIXED-COM/RES", "number_stories": 8}, 30.0,
                       box(-10, -10, 10, 10), 1)
    scene = {"name": "t", "camera": base["camera"], "meters_per_pixel": mpp, "frame_px": SIZE, "frames": [frame],
             "ground": {"image": "output/_test_render/ground.png", "extent_m": [-100, -100, 100, 100],
                        "uv_poly": {"u": [0.005, 0, 0.5, 0, 0, 0], "v": [0, 0.005, 0.5, 0, 0, 0]}},
             "trees": []}
    (root / "plain.json").write_text(json.dumps({**scene, "buildings": [building]}))
    (root / "facade.json").write_text(json.dumps({**scene, "buildings": [{**building, "facade": compact(spec)}]}))
    # The renderer as it was before façades, for the no-facade comparison
    old = root / "old"
    old.mkdir()
    (old / "render.js").write_text(subprocess.run(["git", "show", "HEAD:render/render.js"], cwd=REPO_ROOT,
                                                  capture_output=True, text=True, check=True).stdout)
    shutil.copy(REPO_ROOT / "render" / "index.html", old / "index.html")
    (old / "vendor").symlink_to(REPO_ROOT / "render" / "vendor")
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _render(scene_rel, mode="color", page="render/index.html"):
    with Renderer(scene_rel, SIZE, page=page) as r:
        return np.asarray(r.frame(0, mode)).astype(int)


def test_windows_on_walls_not_roofs_and_masks_unchanged(scenes):
    plain = _render("output/_test_render/plain.json")
    fac = _render("output/_test_render/facade.json")
    gray = np.array(GRAY)
    walls = np.abs(plain - gray).max(axis=2) > 6  # walls are the only non-aerial surfaces
    diff = np.abs(fac - plain).max(axis=2) > 6
    assert walls.sum() > 2000
    # Antialiased wall edges blend into the ground, so allow 2 px around the walls
    near = np.asarray(Image.fromarray(walls.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    assert not (diff & ~near).any(), "roofs and ground are untouched"
    # Two tones on the walls: brick and windows (darker)
    lum = fac[walls].mean(axis=1)
    dark = lum < np.median(lum) - 25
    assert 0.05 < dark.mean() < 0.6, dark.mean()
    assert np.array_equal(_render("output/_test_render/plain.json", "mask"),
                          _render("output/_test_render/facade.json", "mask"))


def test_no_facade_data_renders_exactly_as_before(scenes):
    now = _render("output/_test_render/plain.json")
    before = _render("output/_test_render/plain.json", page="output/_test_render/old/index.html")
    assert np.array_equal(now, before)


def test_porch_band_only_on_street_facing_walls(scenes):
    # Paint only: the porch (roof band, shadowed recess, posts) goes on the
    # walls facing the street (facade "d"). Of four directions, two point at
    # walls the camera sees and change the image; two point at hidden walls
    # and leave it identical to the same building without a porch
    from shapely.geometry import box

    root = scenes
    scene = json.loads((root / "plain.json").read_text())
    rec = {"building_code_description": "ROW 2 STY MASONRY", "building_code_description_new": "ROW PORCH FRONT",
           "number_stories": 2}
    spec = facade_spec(rec, 8.0, box(-10, -10, 10, 10), 1)
    b0 = {**scene["buildings"][0], "h": 8.0}
    no_porch = {**compact(spec), "b": compact(spec)["b"] & ~2}
    (root / "noporch.json").write_text(json.dumps({**scene, "buildings": [{**b0, "facade": no_porch}]}))
    base = _render("output/_test_render/noporch.json")
    changed = []
    for d in ([1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0]):
        f = {**compact(spec), "d": d + [0.0, 0.0]}
        (root / "porch.json").write_text(json.dumps({**scene, "buildings": [{**b0, "facade": f}]}))
        changed.append(int((np.abs(_render("output/_test_render/porch.json") - base).max(axis=2) > 6).sum()))
    assert sorted(c > 50 for c in changed) == [False, False, True, True], changed
    assert sorted(changed)[:2] == [0, 0], changed


# --- Era option (docs/building_age_plan.md, Phase A) ---------------------------

GOLDEN = REPO_ROOT / "tests" / "fixtures" / "render_golden.json"


def _sha(a):
    import hashlib

    return hashlib.sha256(np.ascontiguousarray(a.astype(np.uint8)).tobytes()).hexdigest()


def test_plain_scene_matches_the_stored_golden_render(scenes):
    """A permanent byte-identical check: the git-HEAD comparison above only
    proves something while a change is uncommitted. The checksums were
    recorded with render.js as of Nov. 23, 2026, before the era option, on
    this machine's headless Chromium; a different GPU or Chromium build can
    change pixels, in which case re-record them from a known-good commit:
    PP_RECORD_GOLDEN=1 uv run pytest tests/test_render_facades.py -k golden
    renders with git-HEAD render.js and rewrites the file."""
    import os

    if os.environ.get("PP_RECORD_GOLDEN"):
        old = "output/_test_render/old/index.html"
        GOLDEN.write_text(json.dumps({
            "note": "sha256 of the plain test scene's color and mask renders (fixture in this file), "
                    "recorded from git-HEAD render.js",
            "plain_color": _sha(_render("output/_test_render/plain.json", page=old)),
            "plain_mask": _sha(_render("output/_test_render/plain.json", "mask", page=old))}, indent=1) + "\n")
    gold = json.loads(GOLDEN.read_text())
    assert _sha(_render("output/_test_render/plain.json")) == gold["plain_color"]
    assert _sha(_render("output/_test_render/plain.json", "mask")) == gold["plain_mask"]


def test_facades_without_era_bits_render_as_before(scenes):
    now = _render("output/_test_render/facade.json")
    before = _render("output/_test_render/facade.json", page="output/_test_render/old/index.html")
    assert np.array_equal(now, before)


@pytest.mark.parametrize("bit", [16, 32])
def test_era_bands_paint_walls_only(scenes, bit):
    from shapely.geometry import box

    from pixelphilly.facades import BAND_HEAVY_CORNICE, BAND_PENT

    assert {16: BAND_PENT, 32: BAND_HEAVY_CORNICE}[bit] == bit
    root = scenes
    scene = json.loads((root / "plain.json").read_text())
    rec = {"building_code_description": "ROW 3 STY MASONRY", "building_code_description_new": "ROW TYPICAL",
           "number_stories": 3}
    f = compact(facade_spec(rec, 10.0, box(-10, -10, 10, 10), 1))
    b0 = {**scene["buildings"][0], "h": 10.0}
    (root / "era_off.json").write_text(json.dumps({**scene, "buildings": [{**b0, "facade": f}]}))
    (root / "era_on.json").write_text(json.dumps({**scene, "buildings": [{**b0, "facade": {**f, "b": f["b"] | bit}}]}))
    off = _render("output/_test_render/era_off.json")
    on = _render("output/_test_render/era_on.json")
    walls = np.abs(_render("output/_test_render/plain.json") - np.array(GRAY)).max(axis=2) > 6
    near = np.asarray(Image.fromarray(walls.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5))) > 0
    diff = np.abs(on - off).max(axis=2) > 6
    assert diff.sum() > 30, diff.sum()
    assert not (diff & ~near).any(), "roofs and ground are untouched"
    assert np.array_equal(_render("output/_test_render/era_off.json", "mask"),
                          _render("output/_test_render/era_on.json", "mask"))
