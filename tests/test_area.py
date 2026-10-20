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
