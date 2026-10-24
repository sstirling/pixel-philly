"""Lon/lat -> map image pixels for the browser viewer.

The generator's projection (WGS84 -> local azimuthal-equidistant meters ->
isometric camera) needs pyproj. For the viewer, the same mapping is fitted
once, here, as a cubic polynomial in lon/lat over the area, and the browser
evaluates it (viewer/projection.js). Over a few km the fit is far below a
pixel; fit_lonlat_to_px reports its worst error so a bad fit fails loudly.

Image pixels are mosaic pixels: (0, 0) is the top-left of the lattice
rectangle (frame col 0, row 0), at ground level (h = 0). Street-level pins
therefore sit at the base of buildings, not on their roofs.
"""

from __future__ import annotations

import numpy as np

from .projection import area_setup, render_ground_polygon


def _terms(u, v):
    # Cubic in normalized coordinates; viewer/projection.js uses the same order
    return np.stack([np.ones_like(u), u, v, u * u, u * v, v * v, u**3, u * u * v, u * v * v, v**3], axis=-1)


def _fit(frame, cam, x_origin: float, y_origin: float, bounds, samples: int) -> dict:
    west, south, east, north = bounds
    lon0, lat0 = (west + east) / 2, (south + north) / 2
    su, sv = (east - west) / 2, (north - south) / 2

    lon, lat = np.meshgrid(np.linspace(west, east, samples), np.linspace(south, north, samples))
    lon, lat = lon.ravel(), lat.ravel()
    e, n = frame.to_local(lon, lat)
    sx, sy = cam.world_to_screen(e, n, 0.0)
    px, py = sx - x_origin, sy - y_origin
    A = _terms((lon - lon0) / su, (lat - lat0) / sv)
    cx, *_ = np.linalg.lstsq(A, px, rcond=None)
    cy, *_ = np.linalg.lstsq(A, py, rcond=None)
    err = float(np.max(np.hypot(A @ cx - px, A @ cy - py)))
    if err > 0.5:
        raise RuntimeError(f"lon/lat -> px fit is off by {err:.2f} px (limit 0.5)")
    return {"lon0": lon0, "lat0": lat0, "su": su, "sv": sv, "cx": cx.tolist(), "cy": cy.tolist(),
            "max_error_px": err, "bounds_wgs84": [west, south, east, north]}


def fit_lonlat_to_px(cfg: dict, samples: int = 60) -> dict:
    frame, cam, frames = area_setup(cfg)
    size = cfg["camera"]["frame_px"]
    x_origin = min(f.x0 - f.col * size for f in frames)
    y_origin = min(f.y0 - f.row * size for f in frames)
    return _fit(frame, cam, x_origin, y_origin, render_ground_polygon(cfg).bounds, samples)


def fit_lonlat_to_px_union(cfgs, x_origin: float, y_origin: float, samples: int = 60) -> dict:
    """The fit for one map made from several areas that share a screen space
    (regions.check_same_space). Pixel (0, 0) is the union lattice's corner
    (x_origin, y_origin in screen px, regions.union_lattice) and the fit
    covers the union of the areas' rendered ground. Over South + North
    Philly (~9 x 15 km) the cubic stays far below a pixel (1.4e-6 px)."""
    from shapely.ops import unary_union

    frame, cam, _ = area_setup(cfgs[0])
    bounds = unary_union([render_ground_polygon(c) for c in cfgs]).bounds
    return _fit(frame, cam, x_origin, y_origin, bounds, samples)


def lonlat_to_px(fit: dict, lon, lat):
    A = _terms((np.asarray(lon) - fit["lon0"]) / fit["su"], (np.asarray(lat) - fit["lat0"]) / fit["sv"])
    return A @ np.asarray(fit["cx"]), A @ np.asarray(fit["cy"])
