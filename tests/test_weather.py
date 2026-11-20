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

NOW = 1_795_039_500  # unix s, 5 minutes after OBS (2026-11-18, 5:05 p.m. EST)
DAY = 1_795_021_200  # 2026-11-18, noon EST
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
        page.add_script_tag(content=worker + "\nwindow.W = { weatherKind, weatherRecord, weatherThunder };", type="module")
        page.add_script_tag(content=viewer + "\nwindow.V = { activeWeather, tempReading, textRows, sunIsDown, describeWeather }; window.__ready = true;", type="module")
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
                  "text": "Light Snow", "temp_c": -1.7, "night": True, "thunder": False}


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
    # NOW is 5:05 p.m. EST, after sunset; DAY is noon the same day
    rec = {"observed": DAY - 600, "temp_c": 19, "kind": None, "text": "Clear", "night": False}
    cases = [rec, {**rec, "night": True}, {**rec, "text": "Mostly Cloudy"}, {**rec, "text": "Partly Cloudy"},
             {**rec, "text": "Fog/Mist"}, {**rec, "kind": "rain", "text": "Light Rain"}, {**rec, "kind": "mix"},
             {**rec, "temp_c": -20.6}, {**rec, "temp_c": None}, {**rec, "observed": NOW - 3 * 3600}, None]
    cases = [c if c is None or c is rec or c.get("night") is not True else {**c, "observed": NOW - 600} for c in cases]
    got = js("return arg.cases.map((r) => V.tempReading(r, r && r.observed > arg.day ? arg.now : arg.day));",
             {"cases": cases, "now": NOW, "day": DAY})
    assert [g and (g["f"], g["icon"]) for g in got] == [
        (66, "sun"), (66, "moon"), (66, "cloud"), (66, "sun"), (66, "fog"), (66, "rain"), (66, "snow"),
        (-5, "sun"), None, None, None]


# Sunrise in Philadelphia on Nov. 19, 2026 is about 6:52 a.m. EST (11:52 UTC)
# and sunset about 4:39 p.m. EST (21:39 UTC); times are checked well clear of both
@pytest.mark.parametrize("iso,down", [
    ("2026-11-19T11:30:00Z", True), ("2026-11-19T12:15:00Z", False), ("2026-11-19T17:00:00Z", False),
    ("2026-11-19T21:15:00Z", False), ("2026-11-19T22:00:00Z", True), ("2026-11-20T03:52:00Z", True),
    ("2026-06-21T00:00:00Z", False),  # 8 p.m. EDT on the longest day: still light
])
def test_sun_is_down(js, iso, down):
    from datetime import datetime
    assert js("return V.sunIsDown(arg);", datetime.fromisoformat(iso).timestamp()) is down


def test_badge_night_comes_from_the_clock_not_nws(js):
    # Nov. 19, 2026: NWS's report had no icon (night null) at 10:52 p.m., and the badge showed a sun
    night_now = 1795146720  # 2026-11-20T03:52:00Z
    rec = {"observed": night_now - 600, "temp_c": 10, "kind": None, "text": "", "night": None}
    got = js("return [V.tempReading(arg.rec, arg.now).icon, V.tempReading({...arg.rec, night: false}, arg.now).icon];",
             {"rec": rec, "now": night_now})
    assert got == ["moon", "moon"]


THUNDER_CASES = [  # SYNTHETIC presentWeather rawStrings, written by hand Nov. 19, 2026
    ([], False), (["TSRA"], True), (["+TSRA"], True), (["-TSRA", "BR"], True), (["TS"], True),
    (["VCTS"], False), (["-RA"], False), (["BR"], False), (["TSRASN"], True), (["-SHRA"], False),
]


@pytest.mark.parametrize("raw,thunder", THUNDER_CASES, ids=lambda v: "+".join(v) if isinstance(v, list) else str(v))
def test_python_thunder(raw, thunder):
    assert live.weather_thunder(_pw(raw)) is thunder


def test_worker_thunder_matches(js):
    got = js("return arg.map((c) => W.weatherThunder(c.map((r) => ({rawString: r}))));", [c[0] for c in THUNDER_CASES])
    assert got == [c[1] for c in THUNDER_CASES]


def test_thunderstorm_in_viewer(js):
    rec = {"observed": DAY - 600, "temp_c": 25, "kind": "rain", "intensity": "heavy", "text": "Thunderstorm, Heavy Rain",
           "night": False, "thunder": True}
    dry = {**rec, "kind": None, "intensity": None, "text": "Thunderstorm"}
    got = js("return [V.activeWeather(arg.rec, arg.day), V.activeWeather(arg.dry, arg.day), V.tempReading(arg.rec, arg.day).icon,"
             " V.tempReading(arg.dry, arg.day).icon, V.describeWeather(V.activeWeather(arg.rec, arg.day)),"
             " V.describeWeather(V.activeWeather(arg.dry, arg.day))];", {"rec": rec, "dry": dry, "day": DAY})
    assert got == [{"kind": "rain", "intensity": "heavy", "thunder": True}, {"kind": None, "intensity": "moderate", "thunder": True},
                   "storm", "storm", "Heavy rain and thunder at Philadelphia International Airport.",
                   "Thunder at Philadelphia International Airport."]


def test_pixel_font_covers_what_the_badge_draws(js):
    rows = js("return [V.textRows('-12°F'), V.textRows('PHL'), V.textRows('0123456789')];")
    for r in rows:
        assert len(r) == 5 and len(set(map(len, r))) == 1
    assert len(rows[0][0]) == 5 * 3 + 4  # five glyphs, nothing dropped


def test_viewer_ignores_stale_or_dry_weather(js):
    rec = {"observed": NOW - 600, "kind": "snow", "intensity": "light"}
    got = js("return [V.activeWeather(arg.rec, arg.now), V.activeWeather({...arg.rec, observed: arg.now - 3 * 3600}, arg.now),"
             " V.activeWeather({...arg.rec, kind: null}, arg.now), V.activeWeather(null, arg.now)];", {"rec": rec, "now": NOW})
    assert got == [{"kind": "snow", "intensity": "light", "thunder": False}, None, None, None]
