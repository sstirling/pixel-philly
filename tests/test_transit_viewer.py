"""viewer/transit_core.js: snapping, motion, the El timetable, sprite choice.

Runs the module in Chromium (Playwright), as tests/test_viewer.py does for
projection.js."""

import json

import pytest

from pixelphilly.projection import REPO_ROOT


@pytest.fixture(scope="module")
def js():
    from playwright.sync_api import sync_playwright

    src = (REPO_ROOT / "viewer" / "transit_core.js").read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html></html>")
        page.add_script_tag(content=src + "\nwindow.T = { prepareShape, pointAt, projectOnto, snap, inTunnel, positionOf,"
                                          " planMove, motionAt, nyClock, servicesFor, elTrains, pickByBearing, carLayout,"
                                          " pointInPolygon, describe, invert2, pxToGround, bearingOf, mToPx, pxToM, lengthM, onRoute,"
                                          " RAIL_SNAP_PX, trackCars, isPlaceholder, extendBack, hiddenByTree }; window.__ready = true;", type="module")
        page.wait_for_function("window.__ready === true")

        def run(expr, arg=None):
            return page.evaluate(f"(arg) => {{ const T = window.T; {expr} }}", arg)

        yield run
        browser.close()


# Two directions of one street: eastbound along y = 0, westbound along y = 6
SHAPES = ("const east = T.prepareShape({id: 'E', pts: [0, 0, 1000, 0], tunnels: [[400, 600]]});"
          "const west = T.prepareShape({id: 'W', pts: [1000, 6, 0, 6], tunnels: []});")


def test_point_at_and_projection(js):
    got = js(SHAPES + "return [T.pointAt(east, 250), T.projectOnto(west, 300, 10)];")
    assert got[0]["x"] == pytest.approx(250) and got[0]["y"] == pytest.approx(0)
    assert got[1]["along"] == pytest.approx(700) and got[1]["dist"] == pytest.approx(4)


def test_snap_keeps_a_vehicle_on_its_direction(js):
    # Halfway between the two shapes, a vehicle that was moving east stays on the eastbound shape
    got = js(SHAPES + "const prev = {shape: east, along: 200};"
                      "const s = T.snap([west, east], 260, 3.2, prev); return [s.shape.id, s.along];")
    assert got == ["E", pytest.approx(260)]
    # Without history the nearer shape wins
    assert js(SHAPES + "return T.snap([east, west], 260, 4).shape.id;") == "W"
    # Far from every shape: off-route
    assert js(SHAPES + "return T.snap([east, west], 260, 200);") is None


def test_backward_jump_on_same_shape_is_penalized(js):
    got = js(SHAPES + "const prev = {shape: east, along: 600};"
                      "return T.snap([east, west], 300, 3.4, prev).shape.id;")
    assert got == "W"  # moving 300 px backward on E is unlikely; W is going that way


def test_tunnel(js):
    assert js(SHAPES + "return [T.inTunnel(east, 500), T.inTunnel(east, 700)];") == [True, False]


def test_glide_follows_the_shape_around_a_corner(js):
    got = js("const s = T.prepareShape({id: 'L', pts: [0, 0, 100, 0, 100, 100], tunnels: []});"
             "const a = T.positionOf({shape: s, along: 50}), b = T.positionOf({shape: s, along: 150});"
             "const m = T.planMove(a, b); return [m.kind, T.motionAt(m, 0.5), T.motionAt(m, 1)];")
    assert got[0] == "along"
    assert got[1]["x"] == pytest.approx(100) and got[1]["y"] == pytest.approx(0)  # at the corner, not cutting it
    assert got[2]["x"] == pytest.approx(100) and got[2]["y"] == pytest.approx(50)


def test_long_moves_jump(js):
    got = js("return T.planMove({x: 0, y: 0, angle: 0}, {x: 9000, y: 0, angle: 0}).kind;")
    assert got == "jump"


SCHEDULE = {
    "patterns": [{"shape": "S", "stops": [[0, 0.0], [120, 1000.0], [240, 1500.0]]}],
    "trips": [[0, 8 * 3600, "SA"], [0, 24 * 3600 + 59 * 60, "SA"]],
    "services": {"20261114": ["SA"], "20261115": ["SU"], "20261121": ["SA"]},
}


def _at(js, iso):
    return js("const r = T.elTrains(arg.s, new Date(arg.t)); return r;", {"s": SCHEDULE, "t": iso})


def test_el_train_at_scheduled_stop_and_between(js):
    # 8:02 a.m. EST = 13:02 UTC: at the second stop; 8:01 halfway to it
    got = _at(js, "2026-11-14T13:02:00Z")
    assert [t["along"] for t in got["trains"]] == [pytest.approx(1000.0)]
    got = _at(js, "2026-11-14T13:01:00Z")
    assert got["trains"][0]["along"] == pytest.approx(500.0)
    assert _at(js, "2026-11-14T13:10:00Z")["trains"] == []  # the trip is over


def test_el_trip_past_midnight_runs_on_the_next_calendar_day(js):
    # Saturday's 24:59 trip is at 12:59 a.m. Sunday (05:59 UTC) and one minute later halfway
    got = _at(js, "2026-11-15T06:00:00Z")
    assert len(got["trains"]) == 1 and got["trains"][0]["along"] == pytest.approx(500.0)


def test_el_falls_back_past_the_end_of_the_timetable(js):
    # Saturday, Jan. 2, 2027 isn't in the timetable: use its last Saturday (Nov. 21)
    got = _at(js, "2027-01-02T13:01:00Z")
    assert got["fallback"] == "20261121" and len(got["trains"]) == 1


def test_ny_clock_handles_daylight_time(js):
    # 4 a.m. UTC on July 1 is midnight in Philadelphia (EDT, UTC-4)
    got = js("return T.nyClock(new Date('2026-07-01T04:00:00Z'));")
    assert got == {"ymd": "20260701", "secs": 0}


def test_point_in_polygon(js):
    sq = [0, 0, 10, 0, 10, 10, 0, 10]
    assert js("return [T.pointInPolygon(arg, 5, 5), T.pointInPolygon(arg, 15, 5)];", sq) == [True, False]


def test_describe(js):
    got = js("return [T.describe({kind: 'bus', route: '23', dest: 'Center City', late: 3}),"
             " T.describe({kind: 'trolley', route: 'T1', dest: '13th St', late: -2}),"
             " T.describe({kind: 'rail', line: 'Trenton', id: '1715', dest: 'Trenton', late: 0}),"
             " T.describe({kind: 'bus', route: '17', dest: '', late: null})];")
    assert got == ["Route 23 bus to Center City, 3 min. late", "Route T1 trolley to 13th St, 2 min. early",
                   "Trenton Line train 1715 to Trenton, on time", "Route 17 bus"]


def test_real_el_schedule_has_trains_on_a_weekday_afternoon(js):
    path = REPO_ROOT / "output" / "philly" / "transit" / "v202611010" / "el_schedule.json"
    if not path.exists():
        pytest.skip("transit files not built on this machine")
    sched = json.loads(path.read_text())
    # Monday, Nov. 16, 2026, 5 p.m. EST: rush hour, the El runs every few minutes both ways
    got = js("return T.elTrains(arg.s, new Date('2026-11-16T22:00:00Z'));", {"s": sched})
    assert got["fallback"] is None
    assert 15 <= len(got["trains"]) <= 60


# --- natural layout (Nov. 14 fix: vehicles looked slanted, train cars uneven on curves) ---------
# The map camera foreshortens: 1 m of ground is 2.4-3.4 map px depending on direction
# (scripts/37_vehicle_sprites.py "ground_to_px"). Layout must happen in meters.
A = [[2.00609301, -2.76115015], [-1.952428, -1.41852197]]  # px = A @ (east, north), the v18 camera


def _kind(n=72, length=16.8, gap=1.0):
    return {"length_m": length, "gap_m": gap, "trucks": [0.15, 0.85],
            "sprites": [{"bearing": i * 360 / n, "id": i} for i in range(n)]}


def _ground_shape(js_points_m):
    # A track given in ground meters, turned into map px with the camera matrix
    return ("const A = arg.A; const toPx = ([e, n]) => [A[0][0] * e + A[0][1] * n, A[1][0] * e + A[1][1] * n];"
            "const pts = arg.pts.flatMap(toPx); const inv = T.invert2(A);"
            "const s = T.prepareShape({id: 'S', pts, tunnels: []}, inv);")


def test_cars_are_evenly_spaced_in_meters_whatever_the_direction(js):
    # Due north then due east: the two legs have different px per meter on screen
    pts = [[0, 0], [0, 300], [300, 300]]
    got = js(_ground_shape(pts) + "const cars = T.carLayout(s, T.mToPx(s, 290), arg.kind, 6, inv);"
             "return cars.map(c => T.pxToGround(inv, c.x, c.y).concat([c.sprite.bearing]));",
             {"A": A, "pts": pts, "kind": _kind()})
    assert len(got) == 6
    # Centers 17.8 m apart along the track (car length + gap)
    import math
    for a, b in zip(got, got[1:]):
        if a[0] < 1 and b[0] < 1:  # both on the straight north leg
            assert math.dist(a[:2], b[:2]) == pytest.approx(17.8, abs=0.05)
    # On the straight north leg every car points due north, with the same sprite
    north = [c for c in got if c[1] < 280]
    assert north and all(c[2] == 0 for c in north)


def test_car_on_a_curve_sits_on_the_chord_between_its_trucks(js):
    import math
    # A 90-degree arc of radius 50 m (a tight El curve), north then turning east
    arc = [[50 - 50 * math.cos(math.radians(t)), 50 * math.sin(math.radians(t))] for t in range(0, 91, 3)]
    pts = [[0, -100]] + arc + [[150, 50]]
    got = js(_ground_shape(pts) + "const L = T.lengthM(s); const cars = T.carLayout(s, T.mToPx(s, 100 + 39), arg.kind, 1, inv);"
             "const c = cars[0]; return [T.pxToGround(inv, c.x, c.y), c.sprite.bearing, c.bearing];",
             {"A": A, "pts": pts, "kind": _kind()})
    (e, n), sprite_bearing, bearing = got
    # Halfway around the arc the car points about 45 degrees (north-east), not 0 or 90
    assert 35 < bearing < 55
    assert abs(sprite_bearing - bearing) <= 2.5  # 72 headings: within half a 5-degree step
    # The car's center is inside the curve (on the chord), not on the rail
    assert math.hypot(e - 50, n - 0) < 50


def test_pick_by_bearing_wraps(js):
    sprites = _kind(n=8)["sprites"]
    assert js("return T.pickByBearing(arg, 350).bearing;", sprites) == 0
    assert js("return T.pickByBearing(arg, 100).bearing;", sprites) == 90


def test_glide_is_steady_in_meters(js):
    # Along an L whose legs differ in px per meter, halfway in time is halfway in meters
    pts = [[0, 0], [0, 100], [100, 100]]
    got = js(_ground_shape(pts) + "const a = T.positionOf({shape: s, along: T.mToPx(s, 50)}, 0, 0, 0, inv);"
             "const b = T.positionOf({shape: s, along: T.mToPx(s, 150)}, 0, 0, 0, inv);"
             "const m = T.planMove(a, b, inv); const p = T.motionAt(m, 0.5); return T.pxToM(s, p.along);",
             {"A": A, "pts": pts})
    assert got == pytest.approx(100, abs=0.1)


def test_snapping_onto_the_road_does_not_turn_the_vehicle_sideways(js):
    # A bus 6 px beside its eastbound shape, heading east, snaps onto it: the short
    # sideways hop must not become its heading
    pts = [[0, 0], [300, 0]]
    got = js(_ground_shape(pts) + "const p = T.mToPx(s, 100); const at = T.pointAt(s, p);"
             "const from = {x: at.x, y: at.y - 6, bearing: 90};"
             "const to = T.positionOf({shape: s, along: p}, 0, 0, 0, inv);"
             "const m = T.planMove(from, to, inv); return [T.motionAt(m, 0.3).bearing, to.bearing];",
             {"A": A, "pts": pts})
    assert got[0] == pytest.approx(90, abs=1) and got[1] == pytest.approx(90, abs=1)


def test_a_vehicle_caught_mid_move_onto_its_route_keeps_gliding_along_it(js):
    # Update 1 hops a bus onto its route (a straight "line" move). Update 2 arrives
    # just before that move ends: the bus must glide along the route from there,
    # not fall back to a straight line forever (Nov. 14: no vehicle ever glided)
    pts = [[0, 0], [300, 0]]
    got = js(_ground_shape(pts) + "const p1 = T.mToPx(s, 100), p2 = T.mToPx(s, 140); const at = T.pointAt(s, p1);"
             "const m1 = T.planMove({x: at.x, y: at.y - 6, bearing: 90}, T.positionOf({shape: s, along: p1}), inv);"
             "const mid = T.onRoute(T.motionAt(m1, 0.98), m1);"
             "const m2 = T.planMove(mid, T.positionOf({shape: s, along: p2}), inv); return m2.kind;",
             {"A": A, "pts": pts})
    assert got == "along"


# --- train physics (Nov. 18: trains turned sideways, lost cars, misbehaved by the river) ---------
# A replay of 33 live updates through the viewer found 60% of train frames drawn as a single
# car on a straight-line move: trains only snapped to their own line, only within 60 px, and
# any change of shape (or a step backward) fell back to a straight line.

def test_rail_snaps_to_another_lines_track_but_prefers_its_own(js):
    got = js(SHAPES + "const other = T.prepareShape({id: 'O', pts: [0, 40, 1000, 40], tunnels: []});"
             # On another line's track only: snaps there
             "const a = T.snap([east], 500, 42, null, {others: [other], maxPx: T.RAIL_SNAP_PX});"
             # Shared corridor, own line 10 px off and the other 2 px off: own line wins
             "const b = T.snap([east], 500, 10, null, {others: [T.prepareShape({id: 'O2', pts: [0, 12, 1000, 12], tunnels: []})],"
             " maxPx: T.RAIL_SNAP_PX});"
             "return [a && a.shape.id, b && b.shape.id];")
    assert got == ["O", "E"]


def test_rail_snaps_farther_off_the_track_than_a_bus(js):
    got = js(SHAPES + "return [T.snap([east], 500, -90), T.snap([east], 500, -90, null, {maxPx: T.RAIL_SNAP_PX}) !== null];")
    assert got == [None, True]


def test_a_move_onto_an_overlapping_shape_glides_along_it(js):
    # Two shapes on the same track (e.g. two lines through one corridor): the train moves
    # from A to B and must glide on the track, not collapse into a straight-line move
    got = js("const a = T.prepareShape({id: 'A', pts: [0, 0, 1000, 0], tunnels: []});"
             "const b = T.prepareShape({id: 'B', pts: [200, 3, 1000, 3, 1000, 800], tunnels: []});"
             "const from = T.positionOf({shape: a, along: 300}), to = T.positionOf({shape: b, along: 900});"
             "const m = T.planMove(from, to, undefined, {maxPx: T.RAIL_SNAP_PX, track: true});"
             "const mid = T.motionAt(m, 0.5); return [m.kind, m.shape && m.shape.id, !!mid.shape, Math.round(mid.y)];")
    assert got[:3] == ["along", "B", True]


def test_a_small_step_backward_holds_still(js):
    got = js(SHAPES + "const from = T.positionOf({shape: east, along: 500}), to = T.positionOf({shape: east, along: 480});"
             "const m = T.planMove(from, to, undefined, {track: true}); const p = T.motionAt(m, 0.5), e = T.motionAt(m, 1);"
             "return [m.kind, Math.round(p.along), Math.round(e.along), !!e.shape];")
    assert got == ["along", 500, 500, True]


def test_a_train_is_never_drawn_on_a_straight_line(js):
    # Off every track, or coming onto the track from off it: a jump, never a "line" move
    got = js(SHAPES + "const on = T.positionOf({shape: east, along: 500});"
             "return [T.planMove({x: 500, y: 300, bearing: 0}, on, undefined, {track: true}).kind,"
             " T.planMove(on, {x: 520, y: 300, bearing: 0}, undefined, {track: true}).kind];")
    assert got == ["jump", "jump"]


def test_a_train_entering_a_tunnel_loses_only_the_cars_inside(js):
    # Tunnel on E from 400 to 600 px; lead car's middle at 430 px: cars of 100 px. The lead
    # is underground, the cars behind it are still outside and must stay drawn
    got = js(SHAPES + "const kind = {length_m: 100, gap_m: 0, trucks: [0.15, 0.85], sprites: [{bearing: 90}]};"
             "const cars = T.trackCars(T.positionOf({shape: east, along: 430}), kind, 3, undefined, true);"
             "return cars.map((c) => Math.round(c.along));")
    assert got == [330, 230]


def test_placeholder_train_position_is_recognized(js):
    got = js("return [T.isPlaceholder(-75.1677778, 39.9538889), T.isPlaceholder(-75.167778, 39.953889),"
             " T.isPlaceholder(-75.1660, 39.9530)];")
    assert got == [True, True, False]


def test_a_train_at_the_start_of_its_shape_keeps_its_trailing_cars(js):
    # Six lines' shapes start at 30th Street. A train there sat at its shape's very start
    # and only the lead car was drawn. The shape is extended back along the track that
    # leads into it (another line's shape through the same point, same direction).
    got = js("const lead = T.prepareShape({id: 'IN', pts: [-500, 2, 600, 2], tunnels: [[300, 400]]});"
             "const back = T.prepareShape({id: 'BACK', pts: [600, 0, -500, 0], tunnels: []});"  # opposite direction
             "const s = T.prepareShape({id: 'S', pts: [0, 0, 1000, 0], tunnels: []});"
             "T.extendBack(s, [back, lead]);"
             "const kind = {length_m: 100, gap_m: 0, trucks: [0.15, 0.85], sprites: [{bearing: 90}]};"
             "const all = T.trackCars(T.positionOf({shape: s, along: 50}), kind, 4);"
             "const shown = T.trackCars(T.positionOf({shape: s, along: 50}), kind, 4, undefined, true);"
             "return [s.ext && s.ext.from, all.map((c) => Math.round(c.x)), shown.length];")
    assert got[0] == "IN"
    assert got[1] == [50, -50, -150, -250]  # every car, the trailing ones on the track behind
    assert got[2] == 3  # IN's tunnel (along 300-400, x -200 to -100) hides the car at -150


def test_a_tree_hides_a_vehicle_behind_it_but_not_one_in_front(js):
    # A canopy pixel at map y 100 whose trunk stands 20 px lower (y 120)
    got = js("return [T.hiddenByTree(20, 100, 110), T.hiddenByTree(20, 100, 120), T.hiddenByTree(20, 100, 130),"
             " T.hiddenByTree(0, 100, 50)];")
    # Bus at y 110 (behind the trunk, under the canopy): hidden. Level with it: hidden.
    # At y 130 (in front, nearer the viewer): drawn over the tree. No tree: drawn.
    assert got == [True, True, False, False]
