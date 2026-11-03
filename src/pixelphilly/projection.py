"""Coordinate maths shared by the data scripts, the renderer and the checks.

Three spaces are involved:

1. WGS84 lon/lat (EPSG:4326), how every source dataset is stored.
2. Local east/north/up meters around the center of the area's bbox. An
   azimuthal equidistant projection centered on the bbox is used; over an area
   ~1 km across its scale error is far below one map pixel (0.293 m).
3. Isometric screen pixels for one orthographic camera, the same geometry as
   isometric-nyc and tiny.london: the view is tilted `elevation_deg` down from
   horizontal and turned `view_bearing_deg` clockwise from true north. Screen
   x grows to the right and screen y grows downward (image convention), with
   the local origin at (0, 0).

The three.js renderer receives the camera basis computed here (see
`IsoCamera.three_js_params`), so Python and WebGL agree to the pixel. Every
frame is the same camera with a shifted frustum, which is what lets frames
line up exactly when they are mosaicked.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyproj import Transformer

REPO_ROOT = Path(__file__).resolve().parents[2]

# City of Philadelphia city limits (scripts/04l_fetch_city_limits.py), used
# by configs with "clip_to_city": true. CITY_FETCH_BBOX is the box the fetch
# queries: the whole city (lon -75.280 to -74.956, lat 39.867 to 40.138) with
# a margin.
CITY_LIMITS = REPO_ROOT / "data" / "raw" / "city_limits.geojson"
CITY_FETCH_BBOX = [-75.30, 39.85, -74.94, 40.15]
_CITY_CACHE: dict = {}


def load_config(name: str | None = None) -> dict:
    """Load config/<name>.json. Without a name, the PP_AREA environment
    variable picks the area (default "oldcity"), so every script can run on
    any area unchanged:  PP_AREA=fishtown uv run python scripts/06_render.py
    """
    name = name or os.environ.get("PP_AREA", "oldcity")
    return json.loads((REPO_ROOT / "config" / f"{name}.json").read_text())


def area_dir(cfg: dict, *parts: str) -> Path:
    """output/<area>/<parts...>: everything generated for one area lives
    under its own folder so areas never overwrite each other. (Cross-area
    things, the GPU spend log and trained LoRAs, stay directly in output/.)"""
    return REPO_ROOT.joinpath("output", cfg["name"], *parts)


class LocalFrame:
    """WGS84 <-> local east/north meters, centered on the bbox, or on
    `origin` (lon, lat) when regions must share one screen space."""

    def __init__(self, bbox_wgs84, origin=None):
        west, south, east, north = bbox_wgs84
        if origin is None:
            self.lon0 = (west + east) / 2
            self.lat0 = (south + north) / 2
        else:
            self.lon0, self.lat0 = float(origin[0]), float(origin[1])
        aeqd = (
            f"+proj=aeqd +lat_0={self.lat0} +lon_0={self.lon0} "
            "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        self._fwd = Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
        self._inv = Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)

    def to_local(self, lon, lat):
        return self._fwd.transform(lon, lat)

    def to_wgs84(self, e, n):
        return self._inv.transform(e, n)


@dataclass(frozen=True)
class IsoCamera:
    view_bearing_deg: float
    elevation_deg: float
    meters_per_pixel: float

    @classmethod
    def from_config(cls, cfg: dict) -> "IsoCamera":
        c = cfg["camera"]
        return cls(c["view_bearing_deg"], c["elevation_deg"], c["meters_per_pixel"])

    @property
    def basis(self):
        """(forward, right, up) unit vectors in local ENU coordinates."""
        b = math.radians(self.view_bearing_deg)
        t = math.radians(self.elevation_deg)
        forward = np.array([math.sin(b) * math.cos(t), math.cos(b) * math.cos(t), -math.sin(t)])
        # forward x world-up, normalized: horizontal, pointing to screen right
        right = np.array([math.cos(b), -math.sin(b), 0.0])
        up = np.cross(right, forward)
        return forward, right, up

    def world_to_screen(self, e, n, h=0.0):
        """Local meters -> screen pixels (x right, y down). Accepts arrays."""
        _, right, up = self.basis
        e, n, h = np.asarray(e, float), np.asarray(n, float), np.asarray(h, float)
        sx = (e * right[0] + n * right[1] + h * right[2]) / self.meters_per_pixel
        sy = -(e * up[0] + n * up[1] + h * up[2]) / self.meters_per_pixel
        return sx, sy

    def screen_to_ground(self, sx, sy, h=0.0):
        """Screen pixels -> the local point at height h that projects there."""
        forward, right, up = self.basis
        sx, sy, h = np.asarray(sx, float), np.asarray(sy, float), np.asarray(h, float)
        # Point on the view plane through the origin, then slide along the
        # view direction until it reaches height h.
        px = sx * self.meters_per_pixel
        py = -sy * self.meters_per_pixel
        base = np.multiply.outer(px, right) + np.multiply.outer(py, up)
        s = (h - base[..., 2]) / forward[2]
        pt = base + np.multiply.outer(s, forward)
        return pt[..., 0], pt[..., 1]

    def three_js_params(self, distance_m: float = 3000.0) -> dict:
        """Camera placement for three.js (x = east, y = up, z = -north)."""
        forward, _, _ = self.basis

        def to_three(v):
            return [float(v[0]), float(v[2]), float(-v[1])]

        return {
            "position": to_three(-forward * distance_m),
            "target": [0.0, 0.0, 0.0],
            "up": [0.0, 1.0, 0.0],
            "near": 1.0,
            "far": distance_m * 2,
        }


@dataclass(frozen=True)
class Frame:
    col: int
    row: int
    x0: int  # screen-pixel coordinates of the frame's top-left corner
    y0: int
    size: int

    @property
    def name(self) -> str:
        return f"frame_{self.col:02d}_{self.row:02d}"

    def frustum(self, mpp: float) -> dict:
        """Orthographic frustum in view-space meters (three.js convention)."""
        return {
            "left": self.x0 * mpp,
            "right": (self.x0 + self.size) * mpp,
            "top": -self.y0 * mpp,
            "bottom": -(self.y0 + self.size) * mpp,
        }


def area_screen_polygon(cam: IsoCamera, frame: LocalFrame, bbox_wgs84, max_height_m: float):
    """The bbox as seen on screen: its ground outline and the same outline
    lifted to `max_height_m`, joined (convex hull), so anything up to that
    height standing in the area falls inside."""
    from shapely.geometry import MultiPoint

    west, south, east, north = bbox_wgs84
    e, n = frame.to_local([west, east, east, west], [south, south, north, north])
    pts = []
    for h in (0.0, max_height_m):
        sx, sy = cam.world_to_screen(e, n, h)
        pts.extend(zip(sx, sy))
    return MultiPoint(pts).convex_hull


def swept_screen_polygon(cam: IsoCamera, frame: LocalFrame, ground_wgs84, max_height_m: float):
    """A WGS84 ground (multi)polygon as seen on screen, swept from height 0
    up to `max_height_m`, so anything up to that height standing on it falls
    inside.

    Raising a point moves it straight up the screen by the same amount
    everywhere (world_to_screen is linear), so the swept shape is the
    Minkowski sum of the ground outline with one vertical segment: the
    outline, the outline lifted, and every edge's quad between them. For a
    box this is exactly area_screen_polygon's convex hull; for a concave
    outline such as the city line, a hull would keep frames that only see
    the outside."""
    import shapely
    import shapely.affinity
    from shapely.ops import unary_union

    def to_screen(c):
        e, n = frame.to_local(c[:, 0], c[:, 1])
        sx, sy = cam.world_to_screen(e, n, 0.0)
        return np.column_stack([sx, sy])

    base = shapely.transform(ground_wgs84, to_screen)
    x0, y0 = cam.world_to_screen(0.0, 0.0, 0.0)
    x1, y1 = cam.world_to_screen(0.0, 0.0, max_height_m)
    d = np.array([float(x1 - x0), float(y1 - y0)])
    lifted = shapely.affinity.translate(base, *d)
    polys = getattr(base, "geoms", [base])
    rings = [r for p in polys for r in (p.exterior, *p.interiors)]
    quads = []
    for r in rings:
        c = np.asarray(r.coords)[:, :2]
        a, b = c[:-1], c[1:]
        q = shapely.polygons(np.stack([a, b, b + d, a + d, a], axis=1))
        quads.extend(q[shapely.area(q) > 0])
    return unary_union([base, lifted, *quads])


def frame_lattice(cam: IsoCamera, frame: LocalFrame, bbox_wgs84, size: int, max_height_m: float,
                  clip: bool = False, ground=None):
    """Frames of `size` px that cover the bbox on the ground plus anything up
    to `max_height_m` tall standing on it. Frames sit on a lattice of whole
    multiples of `size` so neighboring frames share edges exactly.

    The lattice is the screen-aligned rectangle around the area. With
    clip=True only frames that actually intersect the area are kept: for a
    large area seen at ~45 degrees, about half the rectangle is empty corner.
    Kept frames keep their rectangle (col, row) so mosaics still line up.

    With `ground` (a WGS84 polygon inside the bbox, e.g. bbox ∩ city limits)
    only frames that see that ground, or anything up to `max_height_m`
    standing on it, are kept (swept_screen_polygon). The rectangle and its
    indices still come from the whole bbox."""
    from shapely.geometry import box

    area = area_screen_polygon(cam, frame, bbox_wgs84, max_height_m)
    xmin, ymin, xmax, ymax = area.bounds
    c0, c1 = math.floor(xmin / size), math.ceil(xmax / size)
    r0, r1 = math.floor(ymin / size), math.ceil(ymax / size)
    frames = [
        Frame(col=c - c0, row=r - r0, x0=c * size, y0=r * size, size=size)
        for r in range(r0, r1)
        for c in range(c0, c1)
    ]
    if ground is not None:
        from shapely.prepared import prep

        seen = prep(swept_screen_polygon(cam, frame, ground, max_height_m))
        frames = [f for f in frames if seen.intersects(box(f.x0, f.y0, f.x0 + size, f.y0 + size))]
    elif clip:
        frames = [f for f in frames if box(f.x0, f.y0, f.x0 + size, f.y0 + size).intersects(area)]
    return frames


def outline_coords(geom) -> np.ndarray:
    """(N, 2) outline coordinates whose extremes bound `geom`: the exterior
    ring of a polygon, or the convex hull's for a multipolygon (a clipped
    render tile's kept frames can form separate pieces)."""
    ring = geom.exterior if geom.geom_type == "Polygon" else geom.convex_hull.exterior
    return np.asarray(ring.coords)


def city_polygon():
    """The city limits as one WGS84 (multi)polygon, from CITY_LIMITS.
    Cached, and re-read when the file changes."""
    import shapely
    from shapely.geometry import shape

    path = Path(CITY_LIMITS)
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run uv run python scripts/04l_fetch_city_limits.py "
                                "(configs with \"clip_to_city\" need it)")
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _CITY_CACHE:
        feats = json.loads(path.read_text())["features"]
        _CITY_CACHE.clear()
        _CITY_CACHE[key] = shapely.union_all([shape(f["geometry"]) for f in feats]).buffer(0)
    return _CITY_CACHE[key]


def city_ground(cfg: dict):
    """bbox ∩ city limits (WGS84) for configs with "clip_to_city": true,
    else None. Regions along the city edge then keep only frames that see
    the city (frame_lattice(ground=...)), and data is fetched for those."""
    if not cfg.get("clip_to_city"):
        return None
    from shapely.geometry import box

    g = box(*cfg["bbox_wgs84"]).intersection(city_polygon())
    if g.is_empty or g.area == 0:
        raise ValueError(f"{cfg.get('name')}: bbox {cfg['bbox_wgs84']} does not intersect the city limits")
    return g


def is_clipped(cfg: dict) -> bool:
    """Does the config keep only part of its frame rectangle? Then data is
    fetched for the kept frames' ground (render_ground_polygon) instead of
    the rectangle's whole extent."""
    return bool(cfg.get("clip_frames_to_area") or cfg.get("clip_to_city"))


def local_frame(cfg: dict) -> LocalFrame:
    """The config's local frame. "projection_origin" ([lon, lat]) puts
    several regions in one screen space, so frames drawn separately sit on
    one global lattice and merge into one map (North Philly uses South
    Philly's origin); without it the origin is the bbox center."""
    return LocalFrame(cfg["bbox_wgs84"], cfg.get("projection_origin"))


def area_setup(cfg: dict):
    """The local frame, camera and frame lattice for a config."""
    frame = local_frame(cfg)
    cam = IsoCamera.from_config(cfg)
    frames = frame_lattice(
        cam, frame, cfg["bbox_wgs84"], cfg["camera"]["frame_px"], cfg["max_height_m"],
        clip=cfg.get("clip_frames_to_area", False), ground=city_ground(cfg),
    )
    return frame, cam, frames


def render_ground_polygon(cfg: dict, margin_m: float = 50.0):
    """Ground seen by the kept frames, as a WGS84 shapely polygon: the union
    of each frame's footprint on the ground, grown by `margin_m`. For clipped
    areas this is what gets downloaded, instead of the whole bounding box.
    With "clip_to_city" the kept frames are those that see the city, so this
    shrinks with them; it still includes the ground those frames show past
    the city line, so no kept frame has a hole in its data."""
    import shapely
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    frame, cam, frames = area_setup(cfg)
    quads = []
    for f in frames:
        x = [f.x0, f.x0 + f.size, f.x0 + f.size, f.x0]
        y = [f.y0, f.y0, f.y0 + f.size, f.y0 + f.size]
        e, n = cam.screen_to_ground(x, y, 0.0)
        quads.append(Polygon(zip(e, n)))
    local = unary_union(quads).buffer(margin_m)
    return shapely.transform(local, lambda c: np.column_stack(frame.to_wgs84(c[:, 0], c[:, 1])))


def render_extent_wgs84(cfg: dict, margin_m: float = 50.0):
    """Ground bbox [west, south, east, north] seen by the whole frame lattice.

    The frames are screen-aligned rectangles around a rotated, tilted view of
    the area, so their corners see ground well outside the area's bbox. Data
    is fetched for this larger extent so no frame has empty ground in it.
    """
    if is_clipped(cfg):
        return list(render_ground_polygon(cfg, margin_m).bounds)
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    x0 = min(f.x0 for f in frames)
    y0 = min(f.y0 for f in frames)
    x1 = max(f.x0 for f in frames) + size
    y1 = max(f.y0 for f in frames) + size
    e, n = cam.screen_to_ground([x0, x1, x1, x0], [y0, y0, y1, y1], 0.0)
    e = np.concatenate([e - margin_m, e + margin_m])
    n = np.concatenate([n - margin_m, n + margin_m])
    lon, lat = frame.to_wgs84(e, n)
    return [float(min(lon)), float(min(lat)), float(max(lon)), float(max(lat))]
