"""Static files for the live transit layer (viewer/transit.js).

The viewer draws SEPTA vehicles on the map. Live positions come from SEPTA's
TransitView (buses, trolleys) and TrainView (Regional Rail) feeds every 15 s;
see worker/septa-live.js. This module builds what doesn't change between
updates, from SEPTA's static GTFS and OpenStreetMap tunnels:

- route shapes in map image pixels, so a vehicle can be snapped onto its
  route and glide along it between updates instead of cutting corners;
- which stretches of each rail or trolley shape are in a tunnel, so the
  viewer hides vehicles there (OSM tunnel ways, matched by railway type and
  direction);
- the Market-Frankford El timetable. SEPTA publishes no live El positions
  (checked Nov. 14, 2026: L1 is in none of TransitView, GTFS-RT vehicle
  positions or GTFS-RT trip updates), so El trains are placed from the
  schedule and the viewer labels them "scheduled."

Distances along shapes are in map image pixels (the same units the viewer
draws in). Vehicles sit at ground level (h = 0): elevated track (the El deck,
rail viaducts) isn't modeled in the scene; it comes from the aerial photo
draped flat, so the drawn track is where the ground-level projection puts it.
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from shapely.geometry import LineString, MultiLineString, box
from shapely.strtree import STRtree

from .viewer_geo import lonlat_to_px

# Equirectangular meters around Philadelphia: plenty for 10 m buffers and
# 5 m spacing over the city (scale error under 0.5% across the map)
LAT0 = 40.0
M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))

DENSIFY_M = 5.0           # spacing for tunnel tests before simplifying
SIMPLIFY_PX = 2.0         # about 0.6 m: well under a vehicle's width
TUNNEL_NEAR_M = 10.0      # a shape point this close to a tunnel way, running the same way, is in it
TUNNEL_ANGLE_DEG = 30.0

# Which OSM railway types can carry each kind of vehicle underground. The
# Market St subway has the El in the middle tracks and the trolleys outside
# them; trolleys may be mapped as tram, light_rail or subway.
TUNNEL_TYPES = {"el": {"subway"}, "trolley": {"tram", "light_rail", "subway"}, "rail": {"rail"}}


def local_m(lon, lat):
    return (np.asarray(lon, float) * M_PER_DEG_LON, np.asarray(lat, float) * M_PER_DEG_LAT)


def lonlat_from_local(x, y):
    return np.asarray(x, float) / M_PER_DEG_LON, np.asarray(y, float) / M_PER_DEG_LAT


# --- GTFS reading ---------------------------------------------------------------
def read_gtfs(path) -> dict:
    """{"bus": {file: [rows]}, "rail": {...}} from SEPTA's gtfs_public.zip,
    which holds google_bus.zip and google_rail.zip."""
    feeds = {}
    with zipfile.ZipFile(path) as outer:
        for feed, inner_name in (("bus", "google_bus.zip"), ("rail", "google_rail.zip")):
            with zipfile.ZipFile(io.BytesIO(outer.read(inner_name))) as inner:
                tables = {}
                for name in ("routes", "trips", "shapes", "stops", "stop_times", "calendar", "calendar_dates"):
                    member = f"{name}.txt"
                    if member in inner.namelist():
                        text = inner.read(member).decode("utf-8-sig")
                        tables[name] = list(csv.DictReader(io.StringIO(text)))
                feeds[feed] = tables
    return feeds


def route_kind(route_id: str, route_type: str) -> str | None:
    """bus, trolley, el or rail; None for routes the layer doesn't draw (the
    Broad Street Line is underground for its whole length in the city)."""
    if route_type == "2":
        return "rail"
    if route_id == "L1":
        return "el"
    if route_id.startswith("B") and route_type == "1":
        return None
    if route_type in ("0", "1"):  # trolleys; M1, the Norristown line, is light metro
        return "trolley"
    if route_type in ("3", "11"):  # 11: trackless trolley (59, 66, 75), drawn as a bus
        return "bus"
    return None


def shapes_by_id(rows) -> dict:
    """shape_id -> (lon array, lat array) in sequence order."""
    pts = defaultdict(list)
    for r in rows:
        pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
    out = {}
    for sid, p in pts.items():
        p.sort()
        out[sid] = (np.array([q[1] for q in p]), np.array([q[2] for q in p]))
    return out


# --- tunnels ----------------------------------------------------------------------
class Tunnels:
    """OSM tunnel ways in local meters, queried by railway type."""

    def __init__(self, osm: dict):
        self.lines, self.types = [], []
        for el in osm.get("elements", []):
            geom = el.get("geometry")
            if el.get("type") != "way" or not geom or len(geom) < 2:
                continue
            x, y = local_m([g["lon"] for g in geom], [g["lat"] for g in geom])
            self.lines.append(LineString(np.column_stack([x, y])))
            self.types.append(el["tags"].get("railway"))
        self.tree = STRtree(self.lines) if self.lines else None

    def flags(self, x, y, kind: str) -> np.ndarray:
        """True for each point (local m) of a shape of `kind` that lies in a
        tunnel: within TUNNEL_NEAR_M of a tunnel way of a matching railway
        type that runs in the same direction (so a surface track crossing
        over a subway, or running beside a tunnel portal, isn't hidden)."""
        n = len(x)
        out = np.zeros(n, bool)
        allowed = TUNNEL_TYPES.get(kind)
        if not allowed or self.tree is None or n < 2:
            return out
        from shapely.geometry import Point
        dx, dy = np.gradient(np.asarray(x, float)), np.gradient(np.asarray(y, float))
        for i in range(n):
            p = Point(x[i], y[i])
            for j in self.tree.query(p.buffer(TUNNEL_NEAR_M)):
                if self.types[j] not in allowed:
                    continue
                line = self.lines[j]
                if line.distance(p) > TUNNEL_NEAR_M:
                    continue
                d = line.project(p)
                a, b = line.interpolate(max(d - 2, 0)), line.interpolate(min(d + 2, line.length))
                tx, ty = b.x - a.x, b.y - a.y
                norm = math.hypot(tx, ty) * math.hypot(dx[i], dy[i])
                if norm == 0:
                    continue
                cos = abs(tx * dx[i] + ty * dy[i]) / norm
                if cos >= math.cos(math.radians(TUNNEL_ANGLE_DEG)):
                    out[i] = True
                    break
        return out


# --- shapes in map pixels ---------------------------------------------------------
def cumulative(pts: np.ndarray) -> np.ndarray:
    seg = np.hypot(*np.diff(pts, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(seg)])


def runs_of(flags) -> list[tuple[int, int, bool]]:
    """[(start index, end index inclusive, flag)] for runs of equal flags;
    neighboring runs share their boundary point so the line stays joined."""
    out, start = [], 0
    for i in range(1, len(flags)):
        if flags[i] != flags[start]:
            out.append((start, i, bool(flags[start])))
            start = i
    out.append((start, len(flags) - 1, bool(flags[start])))
    return out


# OSM tags the Center City rail tunnel in stretches, with gaps at the underground
# stations (Suburban, Jefferson), which are mapped as stations, not tunnel. A train
# stopped there showed a car between skyscrapers (Nov. 18). The shortest open-air
# stretch between two tunnels on these lines is far longer (the Main Line's short
# tunnels under highways are over 500 m apart).
TUNNEL_GAP_M = 250.0


def fill_tunnel_gaps(flags, xy):
    """Mark open stretches shorter than TUNNEL_GAP_M between two tunnel
    stretches as tunnel. flags: per point of xy (local meters, in order)."""
    flags = np.asarray(flags, bool).copy()
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(np.asarray(xy, float), axis=0).T))])
    for a, b, flag in runs_of(flags):
        # runs_of shares end points: an open run between tunnels starts and ends on tunnel points
        if not flag and 0 < a and b < len(flags) - 1 and d[b] - d[a] < TUNNEL_GAP_M:
            flags[a:b + 1] = True
    return flags


SPIKE_MAX_M = 50.0     # out-and-back shorter than this is a drawing error, not a route
SPIKE_RETRACE_M = 2.0  # coming back within this of where it turned off counts as retracing
SPIKE_COS = -0.94      # a turn of more than about 160 degrees


def remove_spikes(x, y):
    """Remove short out-and-back spikes from a shape (local meters).

    Some SEPTA GTFS shapes go a few meters out and come straight back over
    the same points (Wilmington/Newark shape 007201, points 84-88, about 20 m
    near University City). A vehicle laid out on that would fold back on
    itself, and clipping the shape (shapely's intersection) splits it into
    pieces there. A spike is a turn of more than about 160 degrees at the end
    of a stretch of at most SPIKE_MAX_M, after which the path comes back to
    within SPIKE_RETRACE_M of a point on that stretch; everything between is
    removed. Turnarounds that go around a block, U-turns onto another street
    and longer spurs to a terminal are kept. Returns new (x, y) arrays."""
    p = np.column_stack([np.asarray(x, float), np.asarray(y, float)])
    changed = True
    while changed and len(p) > 2:
        changed = False
        keep = np.ones(len(p), bool)
        keep[1:] = np.hypot(*np.diff(p, axis=0).T) > 1e-6  # drop repeated points
        p = p[keep]
        seg = np.diff(p, axis=0)
        length = np.hypot(*seg.T)
        cos = (seg[:-1] * seg[1:]).sum(1) / (length[:-1] * length[1:])
        for apex in np.nonzero(cos < SPIKE_COS)[0] + 1:
            # Points on the way out, up to SPIKE_MAX_M back from the turn
            out, run = [], 0.0
            for k in range(apex - 1, -1, -1):
                run += length[k]
                if run > SPIKE_MAX_M:
                    break
                out.append(k)
            if not out:
                continue
            # The first point on the way back that returns to one of them
            back = 0.0
            for j in range(apex + 1, len(p)):
                back += length[j - 1]
                if back > SPIKE_MAX_M + SPIKE_RETRACE_M:
                    break
                near = [k for k in out if np.hypot(*(p[j] - p[k])) <= SPIKE_RETRACE_M]
                if near:
                    k = max(near)
                    p = np.vstack([p[:k + 1], p[j + 1:]])
                    changed = True
                    break
            if changed:
                break
    return p[:, 0], p[:, 1]


def shape_pieces(lon, lat, fit: dict, clip_box, kind: str, tunnels: Tunnels | None):
    """One GTFS shape -> pieces inside `clip_box` (lon/lat), each
    {"pts": [x0, y0, x1, y1, ...] map px (integers), "tunnels": [[d0, d1], ...]
    px along the piece}. A route that leaves the map and comes back makes
    two pieces."""
    x, y = remove_spikes(*local_m(lon, lat))
    line = LineString(np.column_stack([x, y]))
    bx0, by0 = local_m(clip_box[0], clip_box[1])
    bx1, by1 = local_m(clip_box[2], clip_box[3])
    clipped = line.intersection(box(float(bx0), float(by0), float(bx1), float(by1)))
    parts = [clipped] if isinstance(clipped, LineString) else list(getattr(clipped, "geoms", []))
    out = []
    for part in parts:
        if not isinstance(part, LineString) or part.length < 1:
            continue
        dense = np.asarray(part.segmentize(DENSIFY_M).coords)
        flags = tunnels.flags(dense[:, 0], dense[:, 1], kind) if tunnels else np.zeros(len(dense), bool)
        flags = fill_tunnel_gaps(flags, dense)
        plon, plat = lonlat_from_local(dense[:, 0], dense[:, 1])
        px = np.column_stack(lonlat_to_px(fit, plon, plat))
        pieces_px, tunnel_flags = [], []
        for a, b, flag in runs_of(flags):
            seg = LineString(px[a:b + 1]) if b > a else None
            if seg is None:
                continue
            coords = np.asarray(seg.simplify(SIMPLIFY_PX, preserve_topology=False).coords)
            if pieces_px:
                coords = coords[1:]  # shared with the end of the previous run
            pieces_px.append(coords)
            tunnel_flags.append((len(coords), flag))
        if not pieces_px:
            continue
        pts = np.vstack(pieces_px)
        d = cumulative(pts)
        tunnel_runs, i = [], 0
        for count, flag in tunnel_flags:
            start = max(i - 1, 0)
            end = i + count - 1
            if flag:
                tunnel_runs.append([round(float(d[start]), 1), round(float(d[end]), 1)])
            i += count
        out.append({"pts": [int(round(v)) for v in pts.ravel()], "tunnels": tunnel_runs})
    return out


# --- schedule (the El) ------------------------------------------------------------
def gtfs_seconds(t: str) -> int:
    """GTFS times can pass 24:00:00 for trips that run past midnight."""
    h, m, s = (int(v) for v in t.split(":"))
    return h * 3600 + m * 60 + s


def project_along(pts: np.ndarray, d: np.ndarray, p, start: float = 0.0) -> float:
    """Distance along the polyline (map px) of the point nearest p, searching
    only from `start` on, so a route that doubles back on itself can't send a
    later stop to an earlier pass."""
    best, best_d = math.inf, start
    a, b = pts[:-1], pts[1:]
    ab = b - a
    ll = (ab ** 2).sum(axis=1)
    ll[ll == 0] = 1e-9
    t = np.clip(((p - a) * ab).sum(axis=1) / ll, 0, 1)
    proj = a + ab * t[:, None]
    dist = np.hypot(*(proj - p).T)
    along = d[:-1] + t * np.sqrt(ll)
    ok = along >= start - 1e-6
    if ok.any():
        i = int(np.argmin(np.where(ok, dist, np.inf)))
        best, best_d = dist[i], float(along[i])
    return best_d


def services_by_date(calendar, calendar_dates) -> dict[str, list[str]]:
    """{"YYYYMMDD": [service ids running that day]} over the feed's dates."""
    days = {}
    weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for r in calendar:
        d0 = date(int(r["start_date"][:4]), int(r["start_date"][4:6]), int(r["start_date"][6:]))
        d1 = date(int(r["end_date"][:4]), int(r["end_date"][4:6]), int(r["end_date"][6:]))
        d = d0
        while d <= d1:
            if r[weekday[d.weekday()]] == "1":
                days.setdefault(d.strftime("%Y%m%d"), set()).add(r["service_id"])
            d += timedelta(days=1)
    for r in calendar_dates:
        s = days.setdefault(r["date"], set())
        if r["exception_type"] == "1":
            s.add(r["service_id"])
        else:
            s.discard(r["service_id"])
    return {k: sorted(v) for k, v in sorted(days.items())}


def el_schedule(feed: dict, shapes_px: dict, fit: dict, route_id: str = "L1") -> dict:
    """The El timetable as repeating patterns. A pattern is a shape plus, for
    each stop, [seconds after the trip's first departure, px along the
    shape]; a trip is [pattern index, first departure in seconds after
    midnight, service id]. shapes_px: shape id -> (points (n, 2) map px,
    distance along at each point). Most of the ~970 trips share a few dozen
    patterns, which keeps the file small."""
    stops = {s["stop_id"]: (float(s["stop_lon"]), float(s["stop_lat"])) for s in feed["stops"]
             if s["stop_lon"] and s["stop_lat"]}  # parent stations can have no position
    trips = {t["trip_id"]: t for t in feed["trips"] if t["route_id"] == route_id}
    times = defaultdict(list)
    for st in feed["stop_times"]:
        if st["trip_id"] in trips:
            times[st["trip_id"]].append((int(st["stop_sequence"]), gtfs_seconds(st["departure_time"] or st["arrival_time"]),
                                         st["stop_id"]))
    patterns, index, out_trips = [], {}, []
    fit_cache = {}
    for trip_id, rows in times.items():
        trip = trips[trip_id]
        sid = trip["shape_id"]
        if sid not in shapes_px:
            continue
        pts, d = shapes_px[sid]
        rows.sort()
        t0 = rows[0][1]
        along, start = [], 0.0
        for _, t, stop_id in rows:
            key = (sid, stop_id)
            p = fit_cache.get(key)
            if p is None:
                p = fit_cache[key] = np.array([float(v) for v in lonlat_to_px(fit, *stops[stop_id])])
            start = project_along(pts, d, p, start)
            along.append([t - t0, round(start, 1)])
        key = (sid, tuple(tuple(a) for a in along))
        if key not in index:
            index[key] = len(patterns)
            patterns.append({"shape": sid, "stops": along})
        out_trips.append([index[key], t0, trip["service_id"]])
    out_trips.sort(key=lambda r: (r[2], r[1]))
    return {"route": route_id, "patterns": patterns, "trips": out_trips}
