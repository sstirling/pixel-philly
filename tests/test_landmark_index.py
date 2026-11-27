"""Landmark list builder (scripts/49_landmark_index.py; docs/landmarks_plan.md)."""

import importlib.util
import json

import pytest

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("landmark_index", REPO_ROOT / "scripts" / "49_landmark_index.py")
li = importlib.util.module_from_spec(spec)
spec.loader.exec_module(li)


def _manifest():
    return {"landmarks": [
        {"slug": "a", "name": "A", "wikidata": "Q1", "lon": -75.1, "lat": 39.9, "coord_source": "Wikidata P625"},
        {"slug": "b", "name": "B", "wikidata": "Q2", "lon": -75.2, "lat": 39.95,
         "coord_override": {"lon": -75.21, "lat": 39.96, "source": "City AIS"}},
    ]}


def _selection(additions=()):
    return {"manifest": {"a": {"kit": "church"}, "b": {"kit": "shed", "criticism": "x"}}, "additions": list(additions)}


def test_every_manifest_landmark_needs_a_selection_entry():
    sel = _selection()
    del sel["manifest"]["b"]
    with pytest.raises(KeyError):
        li.build_index(sel, _manifest(), {}, [], lambda lon, lat: "r")


def test_override_wins_and_region_is_assigned():
    out = li.build_index(_selection(), _manifest(), {}, [], lambda lon, lat: "west" if lon < -75.15 else "south")
    b = next(e for e in out if e["slug"] == "b")
    assert (b["lon"], b["lat"], b["coord_source"]) == (-75.21, 39.96, "City AIS")
    assert b["region"] == "west" and b["criticism"] == "x"
    assert next(e for e in out if e["slug"] == "a")["region"] == "south"


def test_additions_use_wikidata_and_check_against_inventory():
    inv = [{"name": "FOO BRG", "id": "f1", "lon": -75.1001, "lat": 39.9, "area": "south"},
           {"name": "FOO BRG", "id": "f2", "lon": -75.3, "lat": 39.9, "area": "south"},
           {"name": "RAIL", "id": "r1", "lon": -75.19, "lat": 39.97, "area": "south"}]
    adds = [{"slug": "foo", "name": "Foo", "wikidata": "Q9", "kit": "bridge_tbd", "inventory": "FOO BRG"},
            {"slug": "rr", "name": "Rail", "wikidata": None, "kit": "bridge_tbd", "inventory": "RAIL",
             "inventory_near": [-75.19, 39.97]}]
    out = li.build_index(_selection(adds), _manifest(), {"Q9": {"label": "Foo", "lon": -75.1, "lat": 39.9}}, inv,
                         lambda lon, lat: "south")
    foo = next(e for e in out if e["slug"] == "foo")
    assert foo["inventory_match"]["id"] == "f1" and foo["inventory_match"]["distance_m"] < 10
    assert "inventory" not in foo and foo["coord_source"] == "Wikidata P625"
    rr = next(e for e in out if e["slug"] == "rr")
    assert (rr["lon"], rr["lat"]) == (-75.19, 39.97) and rr["coord_source"].startswith("bridge inventory")


def test_v18_px_matches_the_viewer_formula():
    fit = {"lon0": 0.0, "lat0": 0.0, "su": 1.0, "sv": 2.0, "cx": [1, 2, 0, 0, 0, 0, 0, 0, 0, 0],
           "cy": [0, 0, 3, 0, 0, 0, 0, 0, 0, 0]}
    assert li.v18_px(fit, 2.0, 4.0) == (5.0, 6.0)


def test_selection_file_covers_the_manifest():
    sel = json.loads(li.SELECTION.read_text())
    man = json.loads(li.MANIFEST.read_text())
    assert {lm["slug"] for lm in man["landmarks"]} <= set(sel["manifest"])
    kits = set(sel["kits"])
    assert all(v["kit"] in kits for v in sel["manifest"].values())
    assert all(a["kit"] in kits for a in sel["additions"])


def test_reviewed_coord_beats_wikidata():
    adds = [{"slug": "u", "name": "U", "wikidata": "Q5", "kit": "bridge_tbd", "inventory": "U ST",
             "coord": {"lon": -75.2, "lat": 39.94, "source": "OSM way 1", "note": "Wikidata off"}}]
    inv = [{"name": "U ST", "id": "u1", "lon": -75.2001, "lat": 39.94, "area": "south"}]
    out = li.build_index(_selection(adds), _manifest(), {"Q5": {"label": "U", "lon": -75.3, "lat": 39.9}}, inv,
                         lambda lon, lat: "south")
    u = next(e for e in out if e["slug"] == "u")
    assert (u["lon"], u["lat"], u["coord_source"]) == (-75.2, 39.94, "OSM way 1")
    assert u["coord_note"] == "Wikidata off" and u["inventory_match"]["distance_m"] < 10 and "coord" not in u


def test_manifest_bridges_keep_the_inventory_check():
    """Bridges moved into the photo manifest (Nov. 26) still get the crossing
    cross-check; the raw selection keys do not leak into the index."""
    sel = _selection()
    sel["manifest"]["a"] = {"kit": "bridge_tbd", "inventory": "FOO BRG"}
    inv = [{"name": "FOO BRG", "id": "f1", "lon": -75.1002, "lat": 39.9, "area": "south"}]
    out = li.build_index(sel, _manifest(), {}, inv, lambda lon, lat: "south")
    a = next(e for e in out if e["slug"] == "a")
    assert a["inventory_match"]["id"] == "f1" and a["inventory_match"]["distance_m"] < 20
    assert "inventory" not in a and "inventory_near" not in a


def test_dropped_entries_stay_out_of_the_index():
    sel = _selection()
    sel["dropped"] = [{"slug": "gone", "name": "Gone", "wikidata": "Q7", "kit": "bridge_tbd",
                       "dropped": {"date": "2026-11-26", "reason": "minor crossing"}}]
    out = li.build_index(sel, _manifest(), {}, [], lambda lon, lat: "south")
    assert "gone" not in {e["slug"] for e in out}


def test_selection_file_dropped_entries_have_reasons():
    sel = json.loads(li.SELECTION.read_text())
    live = set(sel["manifest"]) | {a["slug"] for a in sel["additions"]}
    for d in sel.get("dropped", []):
        assert d["dropped"]["reason"] and d["dropped"]["date"]
        assert d["slug"] not in live
