import itertools

from pixelphilly.projection import REPO_ROOT, area_dir, area_setup, load_config


def test_pp_area_selects_config(monkeypatch):
    monkeypatch.setenv("PP_AREA", "fishtown")
    assert load_config()["name"] == "fishtown"
    monkeypatch.delenv("PP_AREA")
    assert load_config()["name"] == "oldcity"


def test_explicit_name_beats_environment(monkeypatch):
    monkeypatch.setenv("PP_AREA", "fishtown")
    assert load_config("oldcity")["name"] == "oldcity"


def test_area_dir_is_per_area():
    a = area_dir(load_config("oldcity"), "renders")
    b = area_dir(load_config("fishtown"), "renders")
    assert a == REPO_ROOT / "output" / "oldcity" / "renders"
    assert b == REPO_ROOT / "output" / "fishtown" / "renders"


def test_fishtown_lattice_tiles_without_gaps():
    cfg = load_config("fishtown")
    _, _, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    origins = {(f.x0, f.y0) for f in frames}
    xs = sorted({x for x, _ in origins})
    ys = sorted({y for _, y in origins})
    assert origins == set(itertools.product(xs, ys))
    assert all(b - a == size for a, b in zip(xs, xs[1:]))
    assert all(b - a == size for a, b in zip(ys, ys[1:]))


def test_downtown_frames_are_clipped_to_the_area():
    from shapely.geometry import box
    from shapely.ops import unary_union

    from pixelphilly.projection import area_screen_polygon

    cfg = load_config("downtown")
    frame, cam, kept = area_setup(cfg)
    full = area_setup({**cfg, "clip_frames_to_area": False})[2]
    size = cfg["camera"]["frame_px"]
    assert 0 < len(kept) < len(full)
    # Kept frames are a subset of the rectangle lattice, with the same indices
    assert {(f.col, f.row, f.x0, f.y0) for f in kept} <= {(f.col, f.row, f.x0, f.y0) for f in full}
    # ...and together they cover the whole area
    area = area_screen_polygon(cam, frame, cfg["bbox_wgs84"], cfg["max_height_m"])
    covered = unary_union([box(f.x0, f.y0, f.x0 + size, f.y0 + size) for f in kept])
    assert covered.contains(area)


def test_unclipped_areas_unchanged():
    # The three test areas keep their full 6 x 5 lattices
    for name in ("oldcity", "fishtown", "centercity"):
        _, _, frames = area_setup(load_config(name))
        assert len(frames) == 30
