"""Drawing a region next to one already drawn (North Philly beside South).

Areas that share a "projection_origin" sit on one global frame lattice:
frame (x0, y0) screen corners are whole multiples of frame_px in both, so a
frame of the new area that covers the same ground as a drawn frame of the
old one has the same (x0, y0). Those shared frames form the "known band".
The joint sampler holds the band at the old area's drawn pixels
(joint_sampler.joint_denoise(known=...)) so the new area continues them
instead of meeting them at a seam.

Everything here is pure (no model, no I/O) and tested on CPU
(tests/test_regions.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def shared_frames(frames, known_frames) -> dict[str, str]:
    """{frame name in `frames`: frame name in `known_frames`} for frames at
    the same screen corner (x0, y0). Frames are projection.Frame-like
    (attributes name, x0, y0)."""
    by_xy = {(f.x0, f.y0): f.name for f in known_frames}
    return {f.name: by_xy[(f.x0, f.y0)] for f in frames if (f.x0, f.y0) in by_xy}


def _dilate(m: np.ndarray) -> np.ndarray:
    """3x3 binary dilation (one Chebyshev step); scipy isn't a dependency."""
    p = np.pad(m, 1)
    out = np.zeros_like(m)
    for i in range(3):
        for j in range(3):
            out |= p[i:i + m.shape[0], j:j + m.shape[1]]
    return out


def known_mask(frames_cells, known_names, cell: int, ramp: int = 0) -> np.ndarray:
    """[H, W] float32 mask in latent cells for joint_denoise(known=...).

    frames_cells: the run's frames as dicts with "name", "col", "row" (canvas
    position, frames of `cell` x `cell` latent cells). Cells of frames in
    known_names are 1. Cells of the other frames ramp down with Chebyshev
    distance d (in cells) from the nearest known cell: 1 - d / (ramp + 1),
    so exactly `ramp` cells lie strictly between 1 and 0 and the new area is
    pulled toward the band instead of meeting a hard edge. Cells farther
    than `ramp`, and canvas cells no frame covers, are 0.

    The default ramp is 0, a hard edge: in the boundary test a ramp of 8
    blended the two sides' latents into an olive smear (seam ratios 6-8 vs.
    2.0-2.8 without); repair_mask's pass handles the join instead.
    """
    known_names = set(known_names)
    cols = max(f["col"] for f in frames_cells) + 1
    rows = max(f["row"] for f in frames_cells) + 1
    known = np.zeros((rows * cell, cols * cell), bool)
    active = np.zeros_like(known)
    for f in frames_cells:
        sl = (slice(f["row"] * cell, (f["row"] + 1) * cell), slice(f["col"] * cell, (f["col"] + 1) * cell))
        active[sl] = True
        if f["name"] in known_names:
            known[sl] = True
    mask = known.astype(np.float32)
    reached = known.copy()
    for d in range(1, ramp + 1):
        grown = _dilate(reached)
        ring = grown & ~reached
        mask[ring] = 1.0 - d / (ramp + 1)
        reached = grown
    mask[~active] = 0.0
    return mask


def repair_mask(frames_cells, known_names, cell: int, width_cells: int):
    """(fixed [H, W] float32, strip [H, W] bool) for the region-join repair
    pass (tiny.london's repair step, SDEdit-style).

    The boundary test drew each side of the join its own way (a building
    straddling it got a gray roof on the North side and a beige one on the
    South side; seam ratios 2.0-2.8 vs. 0.9-1.6 inside regions), and blending
    latents across the join smeared olive. So after the main pass a strip of
    the NEW frames' cells within `width_cells` (Chebyshev) of a known cell is
    re-noised and redrawn while everything else is held fixed: the model
    sees both finished sides at every step. strip: those cells; fixed: 1
    everywhere else (known cells, the new interior, uncovered canvas)."""
    known_names = set(known_names)
    cols = max(f["col"] for f in frames_cells) + 1
    rows = max(f["row"] for f in frames_cells) + 1
    known = np.zeros((rows * cell, cols * cell), bool)
    new = np.zeros_like(known)
    for f in frames_cells:
        sl = (slice(f["row"] * cell, (f["row"] + 1) * cell), slice(f["col"] * cell, (f["col"] + 1) * cell))
        (known if f["name"] in known_names else new)[sl] = True
    near = known.copy()
    for _ in range(width_cells):
        near = _dilate(near)
    strip = near & new
    return (~strip).astype(np.float32), strip


def repair_step(sigmas, target: float) -> int:
    """Index of the schedule step whose sigma is nearest `target`, where the
    repair pass starts (it runs sigmas[i:] down to 0). The last entry (0) is
    never chosen: the repair needs at least one step."""
    return int(np.argmin([abs(float(s) - target) for s in sigmas[:-1]]))


def lattice_distance(a, b) -> int:
    """Chebyshev distance in frames on the global lattice (x0 // size)."""
    return max(abs(a.x0 // a.size - b.x0 // b.size), abs(a.y0 // a.size - b.y0 // b.size))


def near_known(frames, known_names, n: int, center=None) -> list:
    """Frames for a cheap boundary test, by Chebyshev distance on the global
    lattice (gc = x0 // size, gr = y0 // size).

    With `center` (a frame of `frames`, normally the known frame nearest a
    chosen point): every frame within n of it, known or not. Without: every
    non-known frame within n of a known frame, plus the known frames within
    n of those."""
    known_names = set(known_names)
    cheb = lattice_distance
    if center is not None:
        return [f for f in frames if cheb(f, center) <= n]
    known = [f for f in frames if f.name in known_names]
    new = [f for f in frames if f.name not in known_names and any(cheb(f, k) <= n for k in known)]
    band = [k for k in known if any(cheb(k, f) <= n for f in new)]
    keep = {f.name for f in new + band}
    return [f for f in frames if f.name in keep]


def rebase(frames) -> list[dict]:
    """[{"name", "col", "row"}] with col/row shifted so the subset's
    top-left frame is (0, 0): a canvas for a few frames shouldn't span the
    whole area's lattice."""
    c0 = min(f.col for f in frames)
    r0 = min(f.row for f in frames)
    return [{"name": f.name, "col": f.col - c0, "row": f.row - r0} for f in frames]


def check_same_space(cfgs) -> None:
    """Raise ValueError unless every config shares one screen space: the
    same projection origin (to 1e-9 degrees) and the same camera (view,
    elevation, scale and frame_px), so their frames sit on one lattice."""
    from .projection import local_frame

    first = cfgs[0]
    a = local_frame(first)
    for cfg in cfgs[1:]:
        b = local_frame(cfg)
        if abs(a.lon0 - b.lon0) > 1e-9 or abs(a.lat0 - b.lat0) > 1e-9:
            raise ValueError(f"{first['name']} and {cfg['name']} have different projection origins "
                             f"({a.lon0}, {a.lat0}) vs. ({b.lon0}, {b.lat0}): set the same \"projection_origin\"")
        if cfg["camera"] != first["camera"]:
            raise ValueError(f"{first['name']} and {cfg['name']} have different cameras or frame_px; their "
                             "frames don't line up")


def union_lattice(areas):
    """One map from several areas on the global lattice (gc = x0 // size,
    gr = y0 // size). areas: [(area name, frames)] in precedence order:
    where two areas have a frame at the same cell, the FIRST listed wins
    (South before North, so the known band keeps South's drawn pixels).

    Returns {"cells": {(col, row): (area, frame)}, "gc0", "gr0", "cols",
    "rows", "counts": {area: cells taken}, "x0", "y0"}: col/row are union
    canvas positions and (x0, y0) the screen-pixel corner of cell (0, 0)."""
    taken = {}
    for name, frames in areas:
        for f in frames:
            key = (f.x0 // f.size, f.y0 // f.size)
            if key not in taken:
                taken[key] = (name, f)
    gc0 = min(k[0] for k in taken)
    gr0 = min(k[1] for k in taken)
    size = next(iter(taken.values()))[1].size
    cells = {(gc - gc0, gr - gr0): v for (gc, gr), v in taken.items()}
    counts = {name: 0 for name, _ in areas}
    for name, _ in cells.values():
        counts[name] += 1
    return {"cells": cells, "gc0": gc0, "gr0": gr0, "cols": max(c for c, _ in cells) + 1,
            "rows": max(r for _, r in cells) + 1, "counts": counts, "x0": gc0 * size, "y0": gr0 * size}


def mosaic_origin(frames) -> tuple[int, int]:
    """Screen px of an area's mosaic pixel (0, 0): the corner of its lattice
    rectangle (frame col 0, row 0), whether or not that frame is kept."""
    return (min(f.x0 - f.col * f.size for f in frames), min(f.y0 - f.row * f.size for f in frames))


def ripple_offset(frames, known_frames=None) -> tuple[int, int]:
    """Shift from this area's mosaic coordinates into the known area's.

    Water ripples are placed by a hash of mosaic position
    (waterpaint.ripple_mask), so two areas repainted in their own mosaic
    coordinates would put different ripples on the same water where they
    meet (the Delaware crosses the North/South join at Girard Ave). Adding
    this offset gives every screen pixel the ripple it has in the known
    area. (0, 0) for a single area, so its output is unchanged."""
    if not known_frames:
        return (0, 0)
    (ax, ay), (bx, by) = mosaic_origin(frames), mosaic_origin(known_frames)
    return (ax - bx, ay - by)


@dataclass(frozen=True)
class PlacedFrame:
    """A frame of another area, positioned in this area's mosaic (col/row
    relative to this area's lattice corner; can be negative) but keeping its
    own name, so its files are found in its own area's folders."""
    col: int
    row: int
    x0: int
    y0: int
    size: int
    name: str


def place_frames(known_frames, frames) -> list[PlacedFrame]:
    """known_frames positioned in the mosaic of `frames` (same screen lattice)."""
    ox, oy = mosaic_origin(frames)
    return [PlacedFrame(col=(k.x0 - ox) // k.size, row=(k.y0 - oy) // k.size, x0=k.x0, y0=k.y0, size=k.size,
                        name=k.name) for k in known_frames]


def _band_files(band_dir):
    """{owner area: folder} for a region run's water_band/ (10_repaint_water.py).
    Two layouts: flat, with report.json "known_area" (one known area, as
    north_lidar wrote it), or one subfolder per owning area with
    report.json "owners" (several known areas: South's and North's frame
    names repeat, so their files can't share a folder)."""
    import json

    rep = band_dir / "report.json"
    if not rep.exists():
        return {}
    info = json.loads(rep.read_text())
    if info.get("known_area"):
        return {info["known_area"]: band_dir}
    return {owner: band_dir / owner for owner in info.get("owners", [])}


def cell_sources(u, names, prompt, stage, root, override_from=None):
    """({cell: illustration PNG}, {area: overrides}) for a union (union_lattice).

    Base: the owning area's finished frame
    (output/<owner>/postprocessed/<prompt>/<stage>/<frame>.png). Overrides:
    a region run re-repaints the known band (water_band/, see _band_files)
    to remove the shore line the owner drew along its old lattice edge;
    those files replace the owner's for their cells. override_from (default
    `names`) lists the areas whose water_band/ to read, in precedence order:
    when two re-repaint the same cell, the LATER one wins (it saw more
    context). The merged map (16_build_tiles.py) and a new region's known
    pixels (known_sources) both come from here, so they agree."""
    src = {cell: root / "output" / a / "postprocessed" / prompt / stage / f"{f.name}.png"
           for cell, (a, f) in u["cells"].items()}
    overrides = {}
    for later in override_from or names:
        files = _band_files(root / "output" / later / "postprocessed" / prompt / "water_band")
        n = 0
        for cell, (a, f) in u["cells"].items():
            if a in files and (files[a] / f"{f.name}.png").exists():
                src[cell] = files[a] / f"{f.name}.png"
                n += 1
        if files:
            overrides[later] = n
    return src, overrides


def known_sources(frames, known, prompt, stage, root, override_from=None):
    """{frame name: (owning area, its frame name, PNG)} for this area's frames
    that known areas already drew. known: [(area, frames)] in precedence
    order (a cell several have goes to the first). The PNG is the merged
    map's pixel for that cell (cell_sources, overrides included)."""
    if not known:
        return {}
    u = union_lattice(known)
    src, _ = cell_sources(u, [a for a, _ in known], prompt, stage, root, override_from)
    size = next(iter(u["cells"].values()))[1].size
    out = {}
    for f in frames:
        cell = ((f.x0 - u["x0"]) // size, (f.y0 - u["y0"]) // size)
        if cell in u["cells"]:
            area, kf = u["cells"][cell]
            out[f.name] = (area, kf.name, src[cell])
    return out


def ripple_root(area, known_of) -> str:
    """The area whose mosaic coordinates place water ripples for a chain of
    regions: follow known_of(area) (a list of known areas, first = the one
    it was primarily drawn against, or None) until an area drawn alone
    (South). One reference for all regions, so a screen pixel has the same
    ripple in every area (ripple_offset to the root's frames)."""
    seen = [area]
    while True:
        known = known_of(seen[-1])
        if not known:
            return seen[-1]
        nxt = known[0]
        if nxt in seen:
            raise ValueError(f"known-area cycle: {' -> '.join(seen + [nxt])}")
        seen.append(nxt)


def owner_edges(cells, order=None) -> list[dict]:
    """Frame borders between cells owned by different areas in a union
    (union_lattice()["cells"]: {(col, row): (area, frame)}): one entry per
    shared border, {"pair": "A|B", "a": cell, "b": cell, "axis": "x" (a is
    left of b) or "y" (a is above b)}. Pair names follow `order` (default:
    the areas' order of first appearance in `cells`), so A|B and B|A are one
    pair."""
    if order is None:
        order = []
        for a, _ in cells.values():
            if a not in order:
                order.append(a)
    rank = {a: i for i, a in enumerate(order)}
    out = []
    for (c, r), (a, _) in cells.items():
        for axis, nb in (("x", (c + 1, r)), ("y", (c, r + 1))):
            if nb in cells and cells[nb][0] != a:
                b = cells[nb][0]
                first, second = sorted((a, b), key=lambda n: rank.get(n, len(rank)))
                out.append({"pair": f"{first}|{second}", "a": (c, r), "b": nb, "axis": axis})
    return out


def redraw_plan(frames, shared: dict, redraw, context: int):
    """(run frames, known {name: known name}) for redrawing a few frames of
    an area that is already drawn (15_joint_sample.py --redraw): the listed
    frames are drawn again, and every frame within `context` (Chebyshev, on
    the global lattice) is held at its finished pixels as a known band, so
    the redrawn frames meet their surroundings without seams. `shared` is
    plan_known's {frame: known frame} with the area's own drawing among the
    known areas."""
    redraw = set(redraw)
    names = {f.name for f in frames}
    if redraw - names:
        raise ValueError(f"--redraw frames not in the area: {sorted(redraw - names)}")
    targets = [f for f in frames if f.name in redraw]
    run = [f for f in frames if any(lattice_distance(f, t) <= context for t in targets)]
    known = {f.name: shared[f.name] for f in run if f.name not in redraw and f.name in shared}
    return run, known
