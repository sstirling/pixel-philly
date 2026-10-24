"""The viewer's JavaScript projection must agree with the generator's."""

import json

import numpy as np

from pixelphilly.projection import REPO_ROOT, area_setup, load_config
from pixelphilly.viewer_geo import fit_lonlat_to_px


def test_python_fit_matches_projection():
    cfg = load_config("downtown")
    fit = fit_lonlat_to_px(cfg)
    assert fit["max_error_px"] < 0.5


def test_javascript_matches_python_projection():
    from playwright.sync_api import sync_playwright

    cfg = load_config("downtown")
    fit = fit_lonlat_to_px(cfg)
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    rng = np.random.default_rng(0)
    w, s, e, n = cfg["bbox_wgs84"]
    pts = list(zip(rng.uniform(w, e, 20), rng.uniform(s, n, 20)))
    # City Hall, by name, as a landmark
    pts.append((-75.16359, 39.95233))
    le, ln = frame.to_local([p[0] for p in pts], [p[1] for p in pts])
    sx, sy = cam.world_to_screen(le, ln, 0.0)
    expected = np.column_stack([sx - x_origin, sy - y_origin])

    js = (REPO_ROOT / "viewer" / "projection.js").read_text().replace("export ", "")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(f"<script>{js}</script>")
        got = page.evaluate("([fit, pts]) => pts.map(([lon, lat]) => lonLatToPx(fit, lon, lat))",
                            [json.loads(json.dumps(fit)), [list(map(float, p)) for p in pts]])
        browser.close()
    err = np.hypot(*(np.asarray(got) - expected).T)
    assert err.max() < 0.5, err.max()


def test_union_fit_matches_each_area_fit_plus_its_offset():
    # One map from South and North Philly: a point in either area lands on
    # that area's own pixel, shifted by where its lattice sits in the union
    from pixelphilly.regions import union_lattice
    from pixelphilly.viewer_geo import fit_lonlat_to_px_union, lonlat_to_px

    cfgs = [load_config("south_lidar"), load_config("north_lidar")]
    u = union_lattice([(c["name"], area_setup(c)[2]) for c in cfgs])
    ufit = fit_lonlat_to_px_union(cfgs, u["x0"], u["y0"])
    assert ufit["max_error_px"] < 0.5
    for cfg in cfgs:
        _, _, frames = area_setup(cfg)
        size = cfg["camera"]["frame_px"]
        ox = min(f.x0 - f.col * size for f in frames) - u["x0"]
        oy = min(f.y0 - f.row * size for f in frames) - u["y0"]
        fit = fit_lonlat_to_px(cfg)
        w, s, e, n = cfg["bbox_wgs84"]
        rng = np.random.default_rng(1)
        lon, lat = rng.uniform(w, e, 25), rng.uniform(s, n, 25)
        ax, ay = lonlat_to_px(fit, lon, lat)
        ux, uy = lonlat_to_px(ufit, lon, lat)
        assert np.max(np.hypot(ux - (ax + ox), uy - (ay + oy))) < 0.5
