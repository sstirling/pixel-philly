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
