"""Landmark OSM fetch helpers (scripts/04s_fetch_landmark_osm.py)."""

import importlib.util

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("landmark_osm", REPO_ROOT / "scripts" / "04s_fetch_landmark_osm.py")
lo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lo)

HALL = {"slug": "hall", "kit": "mansard_tower", "lon": -75.1639, "lat": 39.9522}
BRIDGE = {"slug": "brg", "kit": "bridge_tbd", "lon": -75.18, "lat": 39.955}


def test_query_uses_each_radius_and_bridge_ways_only_for_bridges():
    q = lo.query_for([HALL, BRIDGE])
    assert f"around:{lo.RADIUS_M},39.9522,-75.1639" in q
    assert f"around:{lo.BRIDGE_RADIUS_M},39.955,-75.18" in q
    assert q.count('way["bridge"]') == 1 and f'way["bridge"]["bridge"!="no"](around:{lo.BRIDGE_RADIUS_M}' in q
    assert q.startswith("[out:json]") and q.endswith("out tags geom;")


def test_summary_counts_tags_within_radius():
    near = {"type": "way", "tags": {"building:part": "yes", "height": "167", "roof:shape": "pyramidal"},
            "geometry": [{"lon": -75.1639, "lat": 39.9522}, {"lon": -75.1640, "lat": 39.9523}]}
    far = {"type": "way", "tags": {"building:part": "yes", "height": "10"},
           "geometry": [{"lon": -75.10, "lat": 39.95}]}
    tower = {"type": "node", "lon": -75.18, "lat": 39.9551, "tags": {"man_made": "tower"}}
    s = lo.summarize([near, far, tower], [HALL, BRIDGE])
    assert s["hall"]["building_parts"] == 1 and s["hall"]["height"] == 1 and s["hall"]["roof:shape"] == 1
    assert s["hall"]["elements"] == 1
    assert s["brg"]["towers_masts_spires"] == 1 and s["brg"]["building_parts"] == 0


def test_center_handles_relations():
    rel = {"type": "relation", "members": [{"geometry": [{"lon": 0.0, "lat": 0.0}, {"lon": 2.0, "lat": 2.0}]}]}
    assert lo.center(rel) == (1.0, 1.0)
    assert lo.center({"type": "way"}) is None
