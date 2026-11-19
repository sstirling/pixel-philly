"""Live weather: the Worker (worker/septa-live.js weatherKind, weatherRecord) and
its local stand-in (scripts/38_live_feed.py) must agree on what animation an NWS
observation gives, and the viewer (viewer/weather.js activeWeather) must ignore
stale observations.

Cases are synthetic (tests/fixtures/weather/present_weather_cases.json): METAR
weather codes as the National Weather Service reports them in presentWeather."""

import importlib.util
import json

import pytest

from pixelphilly.projection import REPO_ROOT

CASES = json.loads((REPO_ROOT / "tests" / "fixtures" / "weather" / "present_weather_cases.json").read_text())["cases"]
_spec = importlib.util.spec_from_file_location("live_feed", REPO_ROOT / "scripts" / "38_live_feed.py")
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)

NOW = 1_795_039_500  # unix s, 5 minutes after OBS
OBS = {"properties": {"timestamp": "2026-11-18T22:00:00+00:00", "textDescription": "Light Snow",
                      "temperature": {"unitCode": "wmoUnit:degC", "value": -1.7, "qualityControl": "V"},
                      "icon": "https://api.weather.gov/icons/land/night/snow?size=medium",
                      "presentWeather": [{"intensity": "light", "modifier": None, "weather": "snow", "rawString": "-SN",
                                          "inVicinity": False}]}}


def _pw(raw):
    return [{"rawString": r} for r in raw]


@pytest.fixture(scope="module")
def js():
    from playwright.sync_api import sync_playwright

    worker = (REPO_ROOT / "worker" / "septa-live.js").read_text()
    viewer = (REPO_ROOT / "viewer" / "weather.js").read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html></html>")
        page.add_script_tag(content=worker + "\nwindow.W = { weatherKind, weatherRecord };", type="module")
        page.add_script_tag(content=viewer + "\nwindow.V = { activeWeather, tempReading, textRows }; window.__ready = true;", type="module")
        page.wait_for_function("window.__ready === true && !!window.W")

        def run(expr, arg=None):
            return page.evaluate(f"(arg) => {{ const W = window.W, V = window.V; {expr} }}", arg)

        yield run
        browser.close()


@pytest.mark.parametrize("case", CASES, ids=lambda c: "+".join(c["raw"]) or "clear")
def test_python_weather_kind(case):
    assert live.weather_kind(_pw(case["raw"])) == (case["kind"], case["intensity"])


def test_worker_weather_kind_matches(js):
    got = js("return arg.map((c) => W.weatherKind(c.map((r) => ({rawString: r}))));", [c["raw"] for c in CASES])
    assert got == [[c["kind"], c["intensity"]] for c in CASES]


def test_weather_record_matches_and_has_its_fields(js):
    py = live.weather_record(OBS, NOW)
    assert js("return W.weatherRecord(arg.obs, arg.now);", {"obs": OBS, "now": NOW}) == py
    assert py == {"fetched": NOW, "observed": 1795039200, "station": "KPHL", "kind": "snow", "intensity": "light",
                  "text": "Light Snow", "temp_c": -1.7, "night": True}


@pytest.mark.parametrize("temperature,icon,temp_c,night", [
    ({"value": 19, "qualityControl": "V"}, "https://api.weather.gov/icons/land/day/skc?size=medium", 19, False),
    ({"value": 7.2, "qualityControl": "X"}, None, None, None),  # failed NWS quality control
    ({"value": None, "qualityControl": "Z"}, "https://api.weather.gov/icons/land/night/ovc", None, True),
    (None, "", None, None),
])
def test_temperature_and_night_match(js, temperature, icon, temp_c, night):
    obs = {"properties": {**OBS["properties"], "temperature": temperature, "icon": icon}}
    py = live.weather_record(obs, NOW)
    assert (py["temp_c"], py["night"]) == (temp_c, night)
    assert js("return W.weatherRecord(arg.obs, arg.now);", {"obs": obs, "now": NOW}) == py


def test_temp_badge_reading(js):
    rec = {"observed": NOW - 600, "temp_c": 19, "kind": None, "text": "Clear", "night": False}
    cases = [rec, {**rec, "night": True}, {**rec, "text": "Mostly Cloudy"}, {**rec, "text": "Partly Cloudy"},
             {**rec, "text": "Fog/Mist"}, {**rec, "kind": "rain", "text": "Light Rain"}, {**rec, "kind": "mix"},
             {**rec, "temp_c": -20.6}, {**rec, "temp_c": None}, {**rec, "observed": NOW - 3 * 3600}, None]
    got = js("return arg.cases.map((r) => V.tempReading(r, arg.now));", {"cases": cases, "now": NOW})
    assert [g and (g["f"], g["icon"]) for g in got] == [
        (66, "sun"), (66, "moon"), (66, "cloud"), (66, "sun"), (66, "fog"), (66, "rain"), (66, "snow"),
        (-5, "sun"), None, None, None]


def test_pixel_font_covers_what_the_badge_draws(js):
    rows = js("return [V.textRows('-12°F'), V.textRows('PHL'), V.textRows('0123456789')];")
    for r in rows:
        assert len(r) == 5 and len(set(map(len, r))) == 1
    assert len(rows[0][0]) == 5 * 3 + 4  # five glyphs, nothing dropped


def test_viewer_ignores_stale_or_dry_weather(js):
    rec = {"observed": NOW - 600, "kind": "snow", "intensity": "light"}
    got = js("return [V.activeWeather(arg.rec, arg.now), V.activeWeather({...arg.rec, observed: arg.now - 3 * 3600}, arg.now),"
             " V.activeWeather({...arg.rec, kind: null}, arg.now), V.activeWeather(null, arg.now)];", {"rec": rec, "now": NOW})
    assert got == [{"kind": "snow", "intensity": "light"}, None, None, None]
