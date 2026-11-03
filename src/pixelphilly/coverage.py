"""Does the set of regions cover the whole city?

Regions share one global frame lattice (projection_origin), so a cell is
(x0 // size, y0 // size). A cell that shows any city ground (height 0) must
be drawn by some region, or the map has a hole inside the city line. This
is checked before anything is downloaded (scripts/23_preflight_regions.py).
Pure; tested in tests/test_coverage.py.
"""

from __future__ import annotations


def city_cells(cam, frame, city_wgs84, size: int) -> dict[tuple[int, int], float]:
    """{(gx, gy): share of the cell's area that is city ground} for every
    global lattice cell the city's ground outline touches."""
    import math

    import shapely
    from shapely.geometry import box
    from shapely.prepared import prep

    import numpy as np

    def to_screen(c):
        e, n = frame.to_local(c[:, 0], c[:, 1])
        sx, sy = cam.world_to_screen(e, n, 0.0)
        return np.column_stack([sx, sy])

    city = shapely.transform(city_wgs84, to_screen)
    pc = prep(city)
    xmin, ymin, xmax, ymax = city.bounds
    out = {}
    for gy in range(math.floor(ymin / size), math.ceil(ymax / size)):
        for gx in range(math.floor(xmin / size), math.ceil(xmax / size)):
            cell = box(gx * size, gy * size, (gx + 1) * size, (gy + 1) * size)
            if pc.intersects(cell):
                out[(gx, gy)] = cell.intersection(city).area / size**2
    return out


def frames_by_cell(frames) -> dict[tuple[int, int], str]:
    """{(gx, gy): frame name} for projection.Frame-like frames."""
    return {(f.x0 // f.size, f.y0 // f.size): f.name for f in frames}


def uncovered_cells(cells: dict, regions: dict) -> dict:
    """The cells of `cells` that no region's frames cover.
    regions: {name: frames}."""
    have = set()
    for frames in regions.values():
        have |= set(frames_by_cell(frames))
    return {c: v for c, v in cells.items() if c not in have}


def shared_cells(a: dict, b: dict) -> set:
    """Cells two regions both have (frames_by_cell dicts)."""
    return set(a) & set(b)
