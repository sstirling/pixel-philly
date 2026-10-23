"""05_build_scene.py must refuse a ground texture larger than the GPU limit
rather than silently downsampling it (bug found Oct. 20 during the city-scale
review: the README promised a refusal, the code quietly resized)."""

import importlib.util

import pytest
from PIL import Image

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("build_scene", REPO_ROOT / "scripts" / "05_build_scene.py")
build_scene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_scene)


def test_oversize_ground_texture_is_refused():
    limit = build_scene.MAX_TEXTURE_PX
    with pytest.raises(ValueError):
        build_scene.ground_texture(Image.new("RGB", (limit + 1, 16)))


def test_texture_within_limit_is_kept_unchanged():
    img = Image.new("RGB", (64, 32), (10, 20, 30))
    assert build_scene.ground_texture(img) is img


def test_downtown_tiles_fit_gpu_and_cover_each_frame_once():
    import json

    from pixelphilly.projection import area_setup, load_config

    index_path = REPO_ROOT / "data" / "processed" / "downtown_tiles.json"
    if not index_path.exists():
        return  # scenes not built on this machine
    index = json.loads(index_path.read_text())
    assert all(max(t["texture_px"]) <= build_scene.MAX_TEXTURE_PX for t in index)
    names = [n for t in index for n in t["frames"]]
    assert len(names) == len(set(names)), "a frame appears in two tiles"
    _, _, frames = area_setup(load_config("downtown"))
    assert set(names) == {f.name for f in frames}


def test_terrace_parts_skip_the_brick_wall_tint():
    # Seat risers take the seats' own aerial color, so stands don't draw as
    # brick façades; ordinary low walls still get the tint
    tint = {"max_height_m": 20, "color": [150, 82, 62], "mix": 0.55}
    assert build_scene.wall_color([120, 130, 140], 16.0, tint) != [120, 130, 140]
    assert build_scene.wall_color([120, 130, 140], 16.0, tint, terrace=True) == [120, 130, 140]
