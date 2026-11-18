"""The live transit feed: worker/septa-live.js normalize() (run in Chromium)
and its local stand-in, scripts/38_live_feed.py, must agree, and both drop
stale and off-map vehicles.

Fixtures (tests/fixtures/septa/) are real SEPTA TransitViewAll and TrainView
responses from Nov. 14, 2026, cut to a few routes, plus three copies of a
real record edited to test the filters (a report an hour old, one north of
the map, one with SEPTA's 999 "no estimate" lateness)."""

import importlib.util
import json

import pytest

from pixelphilly.projection import REPO_ROOT

FIX = REPO_ROOT / "tests" / "fixtures" / "septa"
_spec = importlib.util.spec_from_file_location("live_feed", REPO_ROOT / "scripts" / "38_live_feed.py")
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)


def _inputs():
    return (json.loads((FIX / "transitview.json").read_text()), json.loads((FIX / "trainview.json").read_text()),
            int((FIX / "fetched.txt").read_text()))


def _js_normalize(tv, rr, now):
    from playwright.sync_api import sync_playwright

    src = (REPO_ROOT / "worker" / "septa-live.js").read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html></html>")
        page.add_script_tag(content=src + "\nwindow.__normalize = normalize; window.__ready = true;", type="module")
        page.wait_for_function("window.__ready === true")
        out = page.evaluate("([tv, rr, now]) => window.__normalize(tv, rr, now)", [tv, rr, now])
        browser.close()
    return out


@pytest.fixture(scope="module")
def outputs():
    tv, rr, now = _inputs()
    return live.normalize(tv, rr, now), _js_normalize(tv, rr, now)


def test_python_and_worker_agree(outputs):
    py, js = outputs
    assert json.dumps(py, sort_keys=True) == json.dumps(js, sort_keys=True)


def test_stale_and_off_map_vehicles_are_dropped(outputs):
    py, _ = outputs
    ids = {v[2] for v in py["vehicles"]}
    assert "STALE" not in ids and "FAR" not in ids
    assert "NOLATE" in ids
    nolate = next(v for v in py["vehicles"] if v[2] == "NOLATE")
    assert nolate[6] is None  # 999 means SEPTA has no estimate


def test_record_shape(outputs):
    py, _ = outputs
    tv, rr, now = _inputs()
    assert py["fetched"] == now
    sources = {v[0] for v in py["vehicles"]}
    assert sources == {"tv", "rr"}
    for v in py["vehicles"]:
        assert len(v) == 10
        lon, lat = v[3], v[4]
        assert live.BOUNDS[0] <= lon <= live.BOUNDS[2] and live.BOUNDS[1] <= lat <= live.BOUNDS[3]
    # Regional Rail: line names, no heading
    rail = [v for v in py["vehicles"] if v[0] == "rr"]
    assert rail and all(v[5] is None for v in rail)


def test_worker_bounds_match_the_map():
    meta = REPO_ROOT / "output" / "philly" / "tiles" / "v18" / "map.json"
    if not meta.exists():
        pytest.skip("v18 tiles not on this machine")
    assert json.loads(meta.read_text())["fit"]["bounds_wgs84"] == live.BOUNDS
    assert str(live.BOUNDS) .replace(" ", "") in (REPO_ROOT / "worker" / "septa-live.js").read_text().replace(" ", "")


def test_trainview_placeholder_position_is_dropped(outputs):
    # TrainView reports trains it can't locate at one fixed point in Suburban Station
    # (39.9538889, -75.1677778), even when their current stop is miles away (7 of 24
    # trains in the fixture, e.g. 1715P at Holmesburg Jct). Observed, not documented.
    fixture = json.loads((FIX / "trainview.json").read_text())
    assert sum((t["lat"], t["lon"]) == ("39.9538889", "-75.1677778") for t in fixture) == 7
    for out in outputs:
        rr = [v for v in out["vehicles"] if v[0] == "rr"]
        assert rr and not any(round(v[3], 5) == -75.16778 and round(v[4], 5) == 39.95389 for v in rr)
