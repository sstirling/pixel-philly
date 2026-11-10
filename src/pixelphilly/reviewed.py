"""Reviewed corrections to source data, applied in the scene build
(scripts/05_build_scene.py).

Some QA hits are errors in the data, not in our rules. Each correction is
an entry someone checked against the 2024 aerial, with the reason, the
source checked and the date; nothing here is inferred automatically.

- config/height_overrides.json: footprints whose City height is wrong.
  "neighbor" gives the footprint the median height of the other footprints
  within NEIGHBOR_RADIUS_M (the default height if there are none);
  "meters" sets a fixed height. An overridden footprint is not LiDAR-shaped
  (b["height_override"]), so the grid can't bring the bad height back.
  First entry: 5458 Tacony St, a ~6 m round object recorded at 138 ft.
- config/stadium_exclusions.json: footprints that pass the stand-terrace
  rule (lidar.stand_terraces) but are not stadiums, e.g. the airport
  terminal and garage complex. Their parts keep ordinary walls.
- config/part_caps.json: a reviewed point, radius and height. LiDAR-shaped
  footprint parts ("<footprint>-<k>") within the radius and taller than
  max_m are dropped; the footprint's other parts stay. For objects the 2022
  LiDAR shaped into a roof that the 2024 aerial shows aren't buildings, e.g.
  the container cranes beside the Walt Whitman Bridge's PA tower.

A footprint not listed is untouched, so areas without entries build
byte-identical scenes. Tested in tests/test_reviewed.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from .projection import REPO_ROOT

HEIGHT_OVERRIDES = REPO_ROOT / "config" / "height_overrides.json"
STADIUM_EXCLUSIONS = REPO_ROOT / "config" / "stadium_exclusions.json"
MODES = ("neighbor", "meters")
NEIGHBOR_RADIUS_M = 25.0


def load(path: Path) -> dict:
    """{str(id): entry} from a reviewed list ({"entries": [...]}); {} if the
    file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return {}
    return {str(e["id"]): e for e in json.loads(path.read_text())["entries"]}


def apply_height_overrides(buildings: list[dict], overrides: dict, default_m: float) -> list[dict]:
    """Apply overrides in place to footprints ({"id", "h", "polys"} in local
    m). Neighbor heights come from the original, unoverridden footprints.
    Returns one QA record per footprint changed."""
    if not overrides:
        return []
    from statistics import median

    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    hits = [i for i, b in enumerate(buildings) if str(b["id"]) in overrides]
    if not hits:
        return []
    geoms = [unary_union([Polygon(p[0], p[1:]) for p in b["polys"]]).buffer(0) for b in buildings]
    tree = STRtree(geoms)
    heights = [b["h"] for b in buildings]
    out = []
    for i in hits:
        b, e = buildings[i], overrides[str(buildings[i]["id"])]
        mode = e.get("mode")
        if mode not in MODES:
            raise ValueError(f"height override for {b['id']}: mode {mode!r} is not one of {MODES}")
        n = 0
        if mode == "meters":
            h = float(e["meters"])
        else:
            near = [heights[k] for k in tree.query(geoms[i], predicate="dwithin", distance=NEIGHBOR_RADIUS_M)
                    if k != i and str(buildings[k]["id"]) not in overrides]
            n = len(near)
            h = float(median(near)) if near else float(default_m)
        out.append({"id": b["id"], "mode": mode, "from_m": b["h"], "to_m": round(h, 2),
                    **({"neighbors": n} if mode == "neighbor" else {})})
        b["h"] = round(h, 2)
        b["ceiling_m"] = None
        b["typical_m"] = None
        b["height_override"] = True
    return out


def stadium_excluded(building_id, exclusions: dict) -> bool:
    return str(building_id) in exclusions


STRUCTURE_EXCLUSIONS = REPO_ROOT / "config" / "structure_exclusions.json"
STRUCTURE_MATCH_M = 5.0


def drop_excluded_structures(parts: list[dict], exclusions: dict, to_local):
    """(kept parts, dropped exclusion ids). LiDAR structure parts ({"region",
    "polys"} in local m) of every region within STRUCTURE_MATCH_M of a
    reviewed point (config/structure_exclusions.json, "lonlat") are dropped.
    to_local: (lon, lat) -> local (e, n)."""
    if not exclusions or not parts:
        return parts, []
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    regions = {}
    for p in parts:
        regions.setdefault(p["region"], []).extend(Polygon(r[0], r[1:]) for r in p["polys"])
    shapes = {k: unary_union(v) for k, v in regions.items()}
    drop, hit = set(), []
    for key, e in exclusions.items():
        pt = Point(*to_local(*e["lonlat"]))
        found = [k for k, g in shapes.items() if g.distance(pt) <= STRUCTURE_MATCH_M]
        if found:
            drop.update(found)
            hit.append(key)
    return [p for p in parts if p["region"] not in drop], hit


PART_CAPS = REPO_ROOT / "config" / "part_caps.json"


def _is_footprint_part(pid) -> bool:
    """LiDAR-shaped footprint part ids are "<footprint>-<k>" strings; single-
    height footprints are ints and structures "s<region>-<k>"."""
    a, sep, b = str(pid).partition("-")
    return bool(sep) and a.isdigit() and b.isdigit()


def drop_capped_parts(parts: list[dict], caps: dict, to_local):
    """(kept parts, {cap id: [dropped part ids]}). A LiDAR-shaped footprint
    part within a cap's radius_m of its reviewed point ("lonlat") and taller
    than its max_m is dropped. to_local: (lon, lat) -> local (e, n)."""
    if not caps or not parts:
        return parts, {}
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    points = {k: (Point(*to_local(*e["lonlat"])), float(e["radius_m"]), float(e["max_m"])) for k, e in caps.items()}
    kept, hit = [], {}
    for b in parts:
        key = None
        if _is_footprint_part(b.get("id")):
            for k, (pt, r, max_m) in points.items():
                if b.get("h", 0) > max_m:
                    g = unary_union([Polygon(p[0], p[1:]).buffer(0) for p in b["polys"]])
                    if g.distance(pt) <= r:
                        key = k
                        break
        if key is None:
            kept.append(b)
        else:
            hit.setdefault(key, []).append(b["id"])
    return kept, hit
