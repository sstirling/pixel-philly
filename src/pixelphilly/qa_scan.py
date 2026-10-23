"""Scene QA scans run before paying for a GPU drawing.

The needle scan turns the one-off check that caught downtown's stray spires
(CHANGELOG, Oct. 23) into a repeatable gate: a part that is small in plan,
tall, and more than twice everything within a few meters is almost always
stray LiDAR returns. Real towers are larger than NEEDLE_MAX_M2, and real
spires and statues rise in small steps from what they stand on, so neither
trips it. Every hit still gets checked against the 2024 aerial by a person;
the scan only finds candidates.
"""

from __future__ import annotations

NEEDLE_MAX_M2 = 40.0  # same size cap as the spike rule in lidar.py
NEEDLE_MIN_H_M = 40.0  # lower slivers don't read as spires at map zoom
NEEDLE_NEAR_M = 3.0  # "around it": parts within this distance
NEEDLE_MIN_JUMP_M = 20.0


def _polygon(part):
    from shapely.geometry import Polygon

    rings = part["polys"][0]
    return Polygon(rings[0], rings[1:])


def find_needles(parts) -> list[dict]:
    """Parts under NEEDLE_MAX_M2, at least NEEDLE_MIN_H_M tall, more than
    twice the tallest part within NEEDLE_NEAR_M and over NEEDLE_MIN_JUMP_M
    above it. parts: scene buildings ({"id", "h", "polys"}) in local meters."""
    from shapely.strtree import STRtree

    geoms = [_polygon(p) for p in parts]
    heights = [p["h"] for p in parts]
    tree = STRtree(geoms)
    hits = []
    for j, (part, g) in enumerate(zip(parts, geoms)):
        h = heights[j]
        if g.area >= NEEDLE_MAX_M2 or h < NEEDLE_MIN_H_M:
            continue
        near = [heights[k] for k in tree.query(g, predicate="dwithin", distance=NEEDLE_NEAR_M) if k != j]
        top = max(near, default=0.0)
        if h > 2 * top and h - top > NEEDLE_MIN_JUMP_M:
            c = g.centroid
            hits.append({"id": part["id"], "h_m": h, "neighbor_max_m": top, "area_m2": round(g.area, 1),
                         "local_xy": [round(c.x, 1), round(c.y, 1)]})
    return hits
