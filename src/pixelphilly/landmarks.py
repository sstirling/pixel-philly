"""Landmark reference windows for the joint sampler (Track 3).

A landmark approved in data/landmarks/manifest.json (status "ok", one
"primary" photo) is drawn with its reference photo as an extra conditioning
image, but only in the joint-sampler windows that have the landmark in their
middle. Every other window keeps the plain conditioning.

Coordinates:
  - lon/lat -> the area's local frame (meters) -> isometric screen pixels,
    lifted to half the landmark's height so a tall building's point sits on
    its body rather than its base (pixelphilly.projection)
  - screen pixels -> CANVAS pixels: the canvas is the frame lattice laid out
    by (col, row), as AreaSampler.joint_volume builds it, so canvas
    (0, 0) is the top-left of frame (col 0, row 0)
  - windows are (y, x) top-left corners in latent cells (8 px), WIN cells
    square (pixelphilly.windows)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pixelphilly.windows import WIN

# The wording that kept geometry in experiment A (scripts/20, prompt "p1"):
# 4 of 4 outputs stayed on the render, against 2 of 4 for a wording that
# named the landmark and called Picture 1 "a photo". The reference is
# Picture 1, the render window Picture 2 (diffusers sizes the output from the
# last image).
PROMPT_P1 = ("Redraw Picture 2 as isometric pixel art in the pixel philly style. The {where} in Picture 2 is "
             "the building shown in Picture 1: match its facade, materials and details, but keep exactly the "
             "shapes and positions of Picture 2.")
WHERE = "large building near the center"


def approved(manifest: dict) -> list[dict]:
    """Landmarks with status "ok" and exactly their "primary" photo."""
    out = []
    for e in manifest["landmarks"]:
        if e.get("status") != "ok":
            continue
        prim = [r for r in e["references"] if r.get("pick") == "primary"]
        if len(prim) != 1 or e.get("lon") is None:
            continue
        r = prim[0]
        # A hand-checked coordinate wins over Wikidata's (e.g. the Water Works,
        # whose Wikidata point sits on the art museum)
        c = e.get("coord_override") or {"lon": e["lon"], "lat": e["lat"]}
        out.append({"slug": e["slug"], "name": e["name"], "lon": c["lon"], "lat": c["lat"],
                    "local_path": r["local_path"], "license": r["license"], "credit": r["credit"],
                    "source_url": r["source_url"]})
    return out


def load_approved(path: Path) -> list[dict]:
    return approved(json.loads(Path(path).read_text()))


def landmark_height(buildings: list[dict], e: float, n: float, radius_m: float = 30.0) -> float:
    """Height of the building at the local point (e, n): the scene footprint
    containing it, or the nearest within radius_m; 0 if none.

    LiDAR splits one footprint into parts with ids "<footprint>-<k>"
    (scripts/05_build_scene.py), so the result is the tallest part sharing
    the nearest part's footprint id. That matters for City Hall: Wikidata's
    point is the courtyard, ~50 m from the 166 m tower, and a plain radius
    would either miss the tower or pick up neighboring skyscrapers."""
    from shapely.geometry import Point, Polygon

    p = Point(e, n)
    best = None
    for b in buildings:
        for poly in b["polys"]:
            d = Polygon(poly[0], poly[1:]).distance(p)
            if d <= radius_m and (best is None or d < best[0]):
                best = (d, b)
    if best is None:
        return 0.0
    key = str(best[1]["id"]).split("-")[0]
    if key.startswith("s"):  # LiDAR-only structure (ships, containers): no footprint group
        return float(best[1]["h"])
    return max(float(b["h"]) for b in buildings if str(b["id"]).split("-")[0] == key)


def canvas_point(frame, cam, frames, lon: float, lat: float, height_m: float) -> tuple[float, float]:
    """Canvas pixel (x, y) of lon/lat lifted to height_m, for an area set up
    with area_setup (frame = LocalFrame, cam = IsoCamera, frames = lattice).
    Frame (col, row) sits at canvas (col * size, row * size) and at screen
    (x0, y0), so the canvas origin in screen pixels is x0 - col * size."""
    f0 = frames[0]
    ox, oy = f0.x0 - f0.col * f0.size, f0.y0 - f0.row * f0.size
    e, n = frame.to_local(lon, lat)
    sx, sy = cam.world_to_screen(e, n, height_m)
    return float(sx) - ox, float(sy) - oy


def frame_at(frames, px: float, py: float):
    """The lattice frame whose canvas square holds canvas pixel (px, py), or None."""
    for f in frames:
        if f.col * f.size <= px < (f.col + 1) * f.size and f.row * f.size <= py < (f.row + 1) * f.size:
            return f
    return None


def in_center(y: int, x: int, px: float, py: float, win: int = WIN, central: float = 0.75) -> bool:
    """Is canvas pixel (px, py) inside the middle `central` fraction of the
    window at latent (y, x)?"""
    side = win * 8
    margin = side * (1 - central) / 2
    return (x * 8 + margin <= px < x * 8 + side - margin) and (y * 8 + margin <= py < y * 8 + side - margin)


def landmark_windows(points: dict[str, tuple[float, float]], grids, win: int = WIN) -> dict[tuple[int, int], str]:
    """{window (y, x): slug}: in EACH grid, the window that contains the
    landmark point and whose center is nearest it.

    One window per grid, because the sampler alternates grids step by step
    (pixelphilly.windows.two_grids): a landmark flagged in only one grid
    would see its reference on half the steps. With a 768 px stride, the
    nearest-centered window has the point within its middle 3/4 (in_center),
    except within 128 px of the canvas edge. If two landmarks want the same
    window, the nearer one gets it and the other takes its next-nearest free
    window in that grid, if any (one reference per window keeps the token
    count bounded). `grids` are the run's grids (active_grids output); edge
    windows can belong to both grids and keep one landmark."""
    half = win * 8 / 2
    out = {}
    for g in grids:
        pairs = sorted((abs(px - (x * 8 + half)) + abs(py - (y * 8 + half)), slug, (y, x))
                       for slug, (px, py) in points.items() for y, x in g
                       if x * 8 <= px < (x + win) * 8 and y * 8 <= py < (y + win) * 8)
        taken, done = set(), set()
        for _, slug, k in pairs:  # greedy, nearest pairs first
            if slug in done or k in taken or out.get(k, slug) != slug:
                continue
            out[k] = slug
            taken.add(k)
            done.add(slug)
    return out


def plan(cfg: dict, manifest_path: Path, scene: dict | None, grids, frames=None) -> dict:
    """Everything the sampler needs for one area: the approved landmarks
    whose point falls on one of the run's frames, their canvas points and
    heights, and the window -> landmark map. `frames` defaults to the full
    lattice; pass the run's frames for a subset."""
    from pixelphilly.projection import area_setup

    frame, cam, all_frames = area_setup(cfg)
    frames = list(frames or all_frames)
    buildings = (scene or {}).get("buildings", [])
    points, info = {}, {}
    for lm in load_approved(manifest_path):
        e, n = frame.to_local(lm["lon"], lm["lat"])
        h = landmark_height(buildings, float(e), float(n)) if buildings else 0.0
        px, py = canvas_point(frame, cam, frames, lm["lon"], lm["lat"], h / 2)
        f = frame_at(frames, px, py)
        if f is None:
            continue
        points[lm["slug"]] = (px, py)
        info[lm["slug"]] = {**lm, "height_m": round(h, 1), "canvas_px": [round(px, 1), round(py, 1)],
                            "frame": f.name}
    windows = landmark_windows(points, grids)
    for slug in info:
        info[slug]["windows"] = sorted([list(k) for k, s in windows.items() if s == slug])
    return {"landmarks": {s: v for s, v in info.items() if v["windows"]}, "windows": windows}


def center_box(px: float, py: float, f, size: int = 512) -> tuple[int, int, int, int]:
    """A size x size box around canvas point (px, py), clamped inside frame f,
    in that frame's own pixel coordinates (for the safety check)."""
    lx, ly = px - f.col * f.size, py - f.row * f.size
    x0 = int(np.clip(round(lx - size / 2), 0, f.size - size))
    y0 = int(np.clip(round(ly - size / 2), 0, f.size - size))
    return x0, y0, x0 + size, y0 + size


def safety_verdict(shift_full, shift_center, edge, edge_baseline, max_shift: int = 2,
                   min_edge_ratio: float = 0.5) -> tuple[bool, str]:
    """Experiment A's rule: reject a landmark-conditioned frame if it moved
    (whole-frame or central shift over max_shift px) or its central edge
    correlation with the render fell below min_edge_ratio x the no-reference
    drawing's (the photo replaced the render's geometry)."""
    if max(map(abs, shift_full)) > max_shift:
        return False, f"whole-frame shift {tuple(shift_full)}"
    if max(map(abs, shift_center)) > max_shift:
        return False, f"central shift {tuple(shift_center)}"
    if edge < min_edge_ratio * edge_baseline:
        return False, f"edge {edge:.3f} < {min_edge_ratio} x baseline {edge_baseline:.3f}"
    return True, "ok"


def edge_corr(a, b) -> float:
    """Zero-shift correlation of edge maps (scripts/20's edge score)."""
    from pixelphilly.qa import _edges

    return float((_edges(a) * _edges(b)).mean())


def check_frame(render, drawn, baseline, box) -> dict:
    """Safety check for one landmark-conditioned frame (PIL images, same
    size): drawn = the run with references, baseline = the same frame drawn
    without them, box = center_box around the landmark. Returns the metrics
    and experiment A's verdict (safety_verdict)."""
    from pixelphilly.qa import registration_shift

    if drawn.size != render.size:
        drawn = drawn.resize(render.size)
    rc, dc, bc = render.crop(box), drawn.crop(box), baseline.crop(box)
    m = {"shift": list(registration_shift(render, drawn)), "shift_center": list(registration_shift(rc, dc)),
         "edge_center": round(edge_corr(rc, dc), 3), "edge_center_baseline": round(edge_corr(rc, bc), 3),
         "box": list(box)}
    m["accepted"], m["reason"] = safety_verdict(m["shift"], m["shift_center"], m["edge_center"],
                                                m["edge_center_baseline"])
    return m
