"""Golf courses from OpenStreetMap (scripts/04n_fetch_golf.py; ODbL,
"© OpenStreetMap contributors").

Stephen (Nov. 3): course fairways came out olive-brown (Byrne: aerial S
~0.61, past the lawn band) or bleached like sand (Saint Martin's: V ~0.86,
S ~0.21), private clubs got no lawn correction (not PPR), and golf ponds
could be "repaired" to grass. This module turns the Overpass JSON into
course outlines and golf feature polygons; the lawn correction
(lawns.correct_golf) and the water repaint use them. Tested in
tests/test_golf.py.

Not courses: disused:/was: courses (Karakung), driving ranges (by name or
under MIN_COURSE_HA), and reviewed construction sites (config/golf.json:
Cobbs Creek "Olde", rebuilt in 2024), which get no lawn correction at all.
"""

from __future__ import annotations

FEATURE_KINDS = ("fairway", "green", "tee", "bunker", "rough", "water_hazard", "lateral_water_hazard")
MIN_COURSE_HA = 5.0


def _geom(e):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union

    if e["type"] == "way" and e.get("geometry"):
        c = [(p["lon"], p["lat"]) for p in e["geometry"]]
        return Polygon(c).buffer(0) if len(c) >= 4 and c[0] == c[-1] else None
    if e["type"] == "relation":
        lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in e.get("members", [])
                 if m.get("geometry") and m.get("role") in ("outer", "") and len(m["geometry"]) >= 2]
        polys = list(polygonize(unary_union(lines))) if lines else []
        return unary_union(polys) if polys else None
    return None


def parse(elements) -> dict:
    """{"courses": [{"id", "name", "tags", "geom"}], "features": {kind: [geom]}}
    with WGS84 shapely geometry; lines and nodes are ignored."""
    courses, feats = [], {}
    for e in elements:
        t = e.get("tags", {})
        g = _geom(e)
        if g is None or g.is_empty:
            continue
        if "golf_course" in (t.get("leisure"), t.get("disused:leisure"), t.get("was:leisure")):
            courses.append({"id": f"{e['type']}/{e['id']}", "name": t.get("name"), "tags": t, "geom": g})
        if t.get("golf") in FEATURE_KINDS:
            feats.setdefault(t["golf"], []).append(g)
    return {"courses": courses, "features": feats}


def _ha(g) -> float:
    import math

    lat = g.centroid.y
    return g.area * 111_320 * 110_574 * math.cos(math.radians(lat)) / 1e4


def courses(parsed, construction=frozenset()) -> list:
    """Active courses: leisure=golf_course, not a driving range (by name or
    under MIN_COURSE_HA) and not a reviewed construction site."""
    out = []
    for c in parsed["courses"]:
        t = c["tags"]
        if t.get("leisure") != "golf_course" or c["id"] in construction:
            continue
        if "driving range" in (c["name"] or "").lower() or _ha(c["geom"]) < MIN_COURSE_HA:
            continue
        out.append(c)
    return out


def construction(parsed, ids) -> list:
    """Reviewed construction courses (config/golf.json), active or disused."""
    return [c for c in parsed["courses"] if c["id"] in ids]


def ppr_construction(ppr_golf, construction_geoms, min_share: float = 0.5) -> list:
    """Indexes of PPR golf properties (PPR parks named "Golf") that lie
    mostly (min_share of their area) over reviewed construction courses.
    The whole property is construction then, not only the OSM outline: the
    PPR "Cobbs Creek Golf Course" property also covers the meadow between
    Olde and Karakung, graded earth in the 2024 aerial (Nov. 4)."""
    from shapely.ops import unary_union

    if not construction_geoms:
        return []
    cons = unary_union(construction_geoms)
    return [i for i, g in enumerate(ppr_golf) if g.area > 0 and g.intersection(cons).area / g.area >= min_share]


def water_hazards(parsed) -> list:
    return parsed["features"].get("water_hazard", []) + parsed["features"].get("lateral_water_hazard", [])
