"""src/pixelphilly/transit.py: static files for the live transit layer."""

import numpy as np
import pytest

from pixelphilly import transit as tr

# A linear lon/lat -> px fit: 1 px per 1e-5 degree, y down (north is up)
FIT = {"lon0": -75.15, "lat0": 39.95, "su": 0.01, "sv": 0.01,
       "cx": [5000.0, 1000.0, 0, 0, 0, 0, 0, 0, 0, 0], "cy": [5000.0, 0, -1000.0, 0, 0, 0, 0, 0, 0, 0]}
BOX = [-75.2, 39.9, -75.1, 40.0]


def test_route_kinds():
    assert tr.route_kind("TRE", "2") == "rail"
    assert tr.route_kind("L1", "1") == "el"
    assert tr.route_kind("B1", "1") is None  # Broad Street Line: underground in the city
    assert tr.route_kind("M1", "1") == "trolley"
    assert tr.route_kind("T1", "0") == "trolley"
    assert tr.route_kind("23", "3") == "bus"
    assert tr.route_kind("66", "11") == "bus"  # trackless trolley


def test_gtfs_seconds_pass_midnight():
    assert tr.gtfs_seconds("25:10:00") == 25 * 3600 + 600
    assert tr.gtfs_seconds("00:00:30") == 30


def test_services_by_date_applies_exceptions():
    cal = [{"service_id": "WK", "monday": "1", "tuesday": "1", "wednesday": "1", "thursday": "1", "friday": "1",
            "saturday": "0", "sunday": "0", "start_date": "20261109", "end_date": "20261115"},
           {"service_id": "SA", "monday": "0", "tuesday": "0", "wednesday": "0", "thursday": "0", "friday": "0",
            "saturday": "1", "sunday": "0", "start_date": "20261109", "end_date": "20261115"}]
    # Veterans Day (Wed. Nov. 11) runs the Saturday schedule
    exc = [{"service_id": "WK", "date": "20261111", "exception_type": "2"},
           {"service_id": "SA", "date": "20261111", "exception_type": "1"}]
    days = tr.services_by_date(cal, exc)
    assert days["20261110"] == ["WK"]
    assert days["20261111"] == ["SA"]
    assert days["20261114"] == ["SA"]
    assert "20261115" not in days or days["20261115"] == []


def test_runs_of_share_boundaries():
    assert tr.runs_of([0, 0, 1, 1, 0]) == [(0, 2, False), (2, 4, True), (4, 4, False)]


def _straight_shape():
    # 1 km due east along lat 39.95, from lon -75.16 to about -75.148
    lon = np.linspace(-75.16, -75.16 + 1000 / tr.M_PER_DEG_LON, 50)
    lat = np.full_like(lon, 39.95)
    return lon, lat


def _osm(ways):
    return {"elements": [{"type": "way", "tags": {"railway": t},
                          "geometry": [{"lon": lo, "lat": la} for lo, la in pts]} for t, pts in ways]}


def test_tunnel_along_half_the_route_is_flagged():
    lon, lat = _straight_shape()
    mid = lon[0] + 500 / tr.M_PER_DEG_LON
    tunnels = tr.Tunnels(_osm([("subway", [(mid, 39.95), (lon[-1] + 0.001, 39.95)])]))
    [piece] = tr.shape_pieces(lon, lat, FIT, BOX, "el", tunnels)
    [[d0, d1]] = piece["tunnels"]
    total = tr.cumulative(np.asarray(piece["pts"], float).reshape(-1, 2))[-1]
    assert d0 == pytest.approx(total / 2, abs=total * 0.02)  # starts at the portal, within one 5 m step
    assert d1 == pytest.approx(total, abs=1)


def test_crossing_tunnel_or_wrong_type_is_not_flagged():
    lon, lat = _straight_shape()
    mid = lon[0] + 500 / tr.M_PER_DEG_LON
    crossing = ("subway", [(mid, 39.94), (mid, 39.96)])  # runs north-south under the route
    beside = ("rail", [(lon[0], 39.95), (lon[-1], 39.95)])  # a Regional Rail tunnel isn't the El's
    tunnels = tr.Tunnels(_osm([crossing, beside]))
    [piece] = tr.shape_pieces(lon, lat, FIT, BOX, "el", tunnels)
    assert piece["tunnels"] == []
    [bus] = tr.shape_pieces(lon, lat, FIT, BOX, "bus", tr.Tunnels(_osm([("subway", [(lon[0], 39.95), (lon[-1], 39.95)])])))
    assert bus["tunnels"] == []  # buses are never hidden


def test_shape_leaving_the_map_splits_into_pieces():
    lon = np.array([-75.15, -75.25, -75.25, -75.15])  # out past the west edge and back
    lat = np.array([39.95, 39.95, 39.96, 39.96])
    pieces = tr.shape_pieces(lon, lat, FIT, BOX, "bus", None)
    assert len(pieces) == 2
    # Ends on the map edge (lon -75.2 -> x = 5000 + 1000 * -5 = 0)
    assert min(pieces[0]["pts"][0::2]) == 0


def test_project_along_never_goes_back():
    # Out east 100 px and back west: the return pass is found only from `start`
    pts = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 2.0], [0.0, 2.0]])
    d = tr.cumulative(pts)
    assert tr.project_along(pts, d, np.array([30.0, 1.0])) == pytest.approx(30.0)
    assert tr.project_along(pts, d, np.array([30.0, 1.0]), start=110) == pytest.approx(172.0)


def test_el_schedule_shares_patterns():
    stops = [{"stop_id": "A", "stop_lon": "-75.150", "stop_lat": "39.95"},
             {"stop_id": "B", "stop_lon": "-75.149", "stop_lat": "39.95"}]
    trips = [{"route_id": "L1", "trip_id": t, "shape_id": "S", "service_id": "SA"} for t in ("1", "2")]
    st = [{"trip_id": "1", "stop_sequence": "1", "departure_time": "08:00:00", "arrival_time": "", "stop_id": "A"},
          {"trip_id": "1", "stop_sequence": "2", "departure_time": "08:02:00", "arrival_time": "", "stop_id": "B"},
          {"trip_id": "2", "stop_sequence": "1", "departure_time": "24:58:00", "arrival_time": "", "stop_id": "A"},
          {"trip_id": "2", "stop_sequence": "2", "departure_time": "25:00:00", "arrival_time": "", "stop_id": "B"}]
    pts = np.array([[5000.0, 5000.0], [5200.0, 5000.0]])
    sched = tr.el_schedule({"stops": stops, "trips": trips, "stop_times": st}, {"S": (pts, tr.cumulative(pts))}, FIT)
    assert len(sched["patterns"]) == 1
    assert sched["patterns"][0]["stops"] == [[0, 0.0], [120, 100.0]]
    assert sched["trips"] == [[0, 8 * 3600, "SA"], [0, 24 * 3600 + 58 * 60, "SA"]]


# --- out-and-back spikes (Nov. 18) -------------------------------------------------------------
# SEPTA's Wilmington/Newark shape 007201 goes out and back over about 20 m near University
# City (points 84-88). Clipping split it into 4 pieces, and trains lost cars there.

def test_out_and_back_spike_is_removed():
    x = np.array([0.0, 250, 270, 250, 500])
    y = np.zeros(5)
    rx, ry = tr.remove_spikes(x, y)
    assert list(rx) == [0, 250, 500] and list(ry) == [0, 0, 0]


def test_retraced_spike_with_overlapping_points_is_removed():
    # The 007201 pattern: A, B, back to near A, A again, B again, then on
    x = np.array([0.0, 100, 120, 102, 100, 120, 300])
    y = np.array([0.0, 0, 5, 0.5, 0, 5, 50])
    rx, ry = tr.remove_spikes(x, y)
    seg = np.diff(np.column_stack([rx, ry]), axis=0)
    cos = (seg[:-1] * seg[1:]).sum(1) / np.hypot(*seg.T)[:-1] / np.hypot(*seg.T)[1:]
    assert (cos > -0.94).all()  # no reversal left
    assert (rx[0], rx[-1]) == (0, 300)


def test_real_turnarounds_are_kept():
    # Around a block: 90-degree turns, not a reversal
    block = (np.array([0.0, 100, 100, 0, 0]), np.array([0.0, 0, 60, 60, 120]))
    # A U-turn onto a parallel street 10 m away: reverses, but doesn't retrace
    uturn = (np.array([0.0, 100, 100, 0]), np.array([0.0, 0, 10, 10]))
    # A long out-and-back (a 200 m spur to a terminal and back) is a real route
    spur = (np.array([0.0, 100, 300, 100, 100]), np.array([0.0, 0, 0, 0, 200]))
    for x, y in (block, uturn, spur):
        rx, ry = tr.remove_spikes(x, y)
        assert list(rx) == list(x) and list(ry) == list(y)


def test_wilmington_shape_is_one_piece():
    import json

    from pixelphilly.projection import REPO_ROOT

    gtfs = REPO_ROOT / "data" / "raw" / "septa_gtfs_v202611010.zip"
    map_json = REPO_ROOT / "output" / "philly" / "tiles" / "v18" / "map.json"
    if not (gtfs.exists() and map_json.exists()):
        pytest.skip("GTFS or v18 map not on this machine")
    fit = json.loads(map_json.read_text())["fit"]
    shapes = tr.shapes_by_id(tr.read_gtfs(gtfs)["rail"]["shapes"])
    pieces = tr.shape_pieces(*shapes["007201"], fit, fit["bounds_wgs84"], "rail", None)
    assert len(pieces) == 1


def test_short_gap_between_tunnels_is_underground():
    # OSM tags the Center City tunnel in stretches with gaps at the underground stations
    # (Suburban, Jefferson): a train stopped there showed a car between skyscrapers.
    # A gap under TUNNEL_GAP_M between two tunnels is underground too; a longer one isn't.
    lon, lat = _straight_shape()
    m = lambda d: lon[0] + d / tr.M_PER_DEG_LON
    near = tr.Tunnels(_osm([("rail", [(m(100), 39.95), (m(400), 39.95)]), ("rail", [(m(500), 39.95), (m(900), 39.95)])]))
    [piece] = tr.shape_pieces(lon, lat, FIT, BOX, "rail", near)
    assert len(piece["tunnels"]) == 1
    far = tr.Tunnels(_osm([("rail", [(m(100), 39.95), (m(300), 39.95)]), ("rail", [(m(700), 39.95), (m(900), 39.95)])]))
    [piece] = tr.shape_pieces(lon, lat, FIT, BOX, "rail", far)
    assert len(piece["tunnels"]) == 2
