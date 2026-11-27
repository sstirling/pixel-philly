"""scripts/19_landmark_refs.py: HABS/HAER measured-drawing listing (--drawings)
and the mapped-area lookup. All network calls are mocked."""

import importlib.util
import json

import pytest

from pixelphilly.projection import REPO_ROOT

spec = importlib.util.spec_from_file_location("landmark_refs", REPO_ROOT / "scripts" / "19_landmark_refs.py")
refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refs)

V18_REGIONS = ["south_lidar", "north_lidar", "upper_north_lidar", "west_lidar", "west_north", "southwest",
               "germantown", "east_riverfront", "roxborough", "lower_northeast", "northwest", "upper_northeast"]


def _group(kind, n, caption):
    """One LoC file group, shaped like the real item JSON (pa0939, Nov. 26, 2026):
    drawing files have type "drawing" and live under /sheet/."""
    path = "sheet" if kind == "drawing" else kind
    base = f"https://tile.loc.gov/storage-services/service/pnp/habshaer/pa/pa0900/pa9999/{path}/{n:05d}"
    return [
        {"mimetype": "image/tiff", "type": kind, "width": 0, "height": 0,
         "url": base.replace("/service/", "/master/") + "a.tif"},
        {"mimetype": "image/jpg", "type": kind, "width": 150, "height": 100, "url": base + "_150px.jpg"},
        {"mimetype": "image/jpeg", "type": kind, "width": 1024, "height": 682, "url": base + "v.jpg"},
        {"mimetype": "application/json", "use": "caption", "title": caption,
         "aka": f"https://www.loc.gov/resource/hhh.pa9999.{path}.{n:05d}a"},
    ]


FAKE_ITEM = {
    "item": {
        "title": "Test Hall, 1 Chestnut Street, Philadelphia, Philadelphia County, PA",
        "call_number": "HABS PA,51-PHILA,999-",
        "medium": ["Photo(s): 1 ", "Measured Drawing(s): 2 "],
    },
    "resources": [
        {"caption": "Photos from Survey HABS PA-9999 ",
         "files": [_group("bw_photos", 1, "HABS PA,51-PHILA,999-1 - Test Hall, GENERAL VIEW FROM SOUTH")]},
        {"caption": "Drawings from Survey HABS PA-9999 ",
         "files": [_group("drawing", 1, "HABS PA,51-PHILA,999- (sheet 1 of 2) - Test Hall"),
                   _group("drawing", 2, "SOUTH ELEVATION - Test Hall. Scale: 1/8\" = 1'-0\"")]},
        {"caption": "Data Pages from Survey HABS PA-9999 ",
         "files": [[{"mimetype": "application/pdf", "type": "data", "width": 1, "height": 1,
                     "url": "https://tile.loc.gov/x/pa9999data.pdf"}]]},
    ],
}


@pytest.fixture
def fake_loc(monkeypatch):
    calls = []

    def get_json(url, kind, post=None):
        calls.append(url)
        assert kind == "loc"
        return FAKE_ITEM

    monkeypatch.setattr(refs, "get_json", get_json)
    return calls


def test_photo_refs_still_exclude_drawing_sheets(fake_loc):
    title, cands = refs.loc_candidates("pa9999")
    assert title.startswith("Test Hall")
    assert len(cands) == 1
    assert "/bw_photos/" in cands[0]["image_url"]
    assert not any("/sheet/" in c["image_url"] for c in cands)


def test_drawings_mode_keeps_the_sheets(fake_loc):
    item = refs.loc_drawings("pa9999")
    sheets = item["sheets"]
    assert [s["sheet"] for s in sheets] == [1, 2]
    assert all("/sheet/" in s["image_url"] for s in sheets)
    assert not any("bw_photos" in s["image_url"] or "data" in s["image_url"] for s in sheets)
    s1 = sheets[0]
    # the largest JPEG, never the TIFF (which is recorded but not downloaded)
    assert s1["image_url"].endswith("v.jpg") and (s1["image_width"], s1["image_height"]) == (1024, 682)
    assert s1["tiff_url"].endswith("a.tif")
    assert s1["caption"].startswith("HABS PA,51-PHILA,999- (sheet 1 of 2)")
    assert s1["source_url"] == "https://www.loc.gov/resource/hhh.pa9999.sheet.00001a"
    assert "public domain" in s1["credit"].lower() and "HABS PA-9999" in s1["credit"]
    assert item["survey"] == "HABS PA-9999"
    assert item["drawings_in_metadata"] == 2 and item["item_url"] == "https://www.loc.gov/item/pa9999/"


def test_scale_is_recorded_only_when_stated(fake_loc):
    s1, s2 = refs.loc_drawings("pa9999")["sheets"]
    assert s1["scale"] is None
    assert s2["scale"] == "1/8\" = 1'-0\""


@pytest.mark.parametrize("text,want", [
    ("Plan. Scale 1:100", "1:100"),
    ("NORTH ELEVATION SCALE: 1/4\" = 1'-0\"", "1/4\" = 1'-0\""),
    ("(sheet 3 of 9) - Christ Church", None),
])
def test_scale_parser(text, want):
    assert refs.scale_from_text(text) == want


def test_drawing_mode_writes_no_files_besides_json(fake_loc, monkeypatch, tmp_path):
    """--drawings must not download anything (no urlopen for images)."""
    monkeypatch.setattr(refs.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("download attempted")))
    refs.loc_drawings("pa9999")


# --- LoC search for landmarks without loc_items ---

def _result(item_id, title, desc="Photo(s): 3 | Measured Drawing(s): 4"):
    return {"id": f"http://www.loc.gov/item/{item_id}/", "title": title, "description": [desc]}


@pytest.mark.parametrize("title,address,want", [
    # name leads the title and the address agrees or is absent: clear
    ("Rodin Museum, 2151 Benjamin Franklin Parkway, Philadelphia, Philadelphia County, PA",
     "2151 BENJAMIN FRANKLIN PKWY", "clear"),
    ("Rodin Museum, Benjamin Franklin Parkway, Philadelphia, Philadelphia County, PA", None, "clear"),
    # same name, different building (the old Franklin Institute on Seventh Street)
    ("Franklin Institute, 15 South Seventh Street, Philadelphia, Philadelphia County, PA",
     "222 N 20TH ST", "uncertain"),
    # a part of the landmark, not the landmark
    ("Rodin Museum, Gate House, 2151 Benjamin Franklin Parkway, Philadelphia, Philadelphia County, PA",
     "2151 BENJAMIN FRANKLIN PKWY", "uncertain"),
    # name words present but not leading
    ("Benjamin Franklin Parkway, Rodin Museum Gardens, Philadelphia, Philadelphia County, PA", None, "uncertain"),
    # outside Philadelphia
    ("Rodin Museum, Meudon, France", None, None),
    # unrelated
    ("John Bartram House, 54th Street, Philadelphia, Philadelphia County, PA", None, None),
])
def test_match_kind(title, address, want):
    assert refs.match_kind(title, ["Rodin Museum", "Franklin Institute"], address) == want


def test_search_sorts_clear_and_uncertain(monkeypatch):
    results = {"results": [
        _result("pa0001", "Rodin Museum, 2151 Benjamin Franklin Parkway, Philadelphia, Philadelphia County, PA"),
        _result("pa0002", "Rodin Museum, Gate House, Philadelphia, Philadelphia County, PA"),
        _result("pa0003", "John Bartram House, 54th Street, Philadelphia, Philadelphia County, PA"),
    ]}
    seen = []

    def get_json(url, kind, post=None):
        seen.append(url)
        return results

    monkeypatch.setattr(refs, "get_json", get_json)
    clear, uncertain, queries = refs.loc_search("rodin_museum", "Rodin Museum", "2151 BENJAMIN FRANKLIN PKWY")
    assert [c["item"] for c in clear] == ["pa0001"]
    assert [u["item"] for u in uncertain] == ["pa0002"]
    assert clear[0]["drawings_in_metadata"] == 4
    assert queries == ["Rodin Museum Philadelphia"]
    assert all("historic-american-buildings" in u and "fo=json" in u for u in seen)


# --- mapped areas ---

def test_mapped_areas_are_the_v18_regions(tmp_path, monkeypatch):
    """Regions come from the frozen v18 list, bboxes from each region's config;
    a retired config (downtown_lidar) that is not in v18 is ignored."""
    (tmp_path / "output" / "philly").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "output" / "philly" / "FROZEN_v18.json").write_text(
        json.dumps({"regions_in_precedence_order": ["south_lidar", "west_north"]}))
    for name, bbox in [("south_lidar", [1, 2, 3, 4]), ("west_north", [5, 6, 7, 8]),
                       ("downtown_lidar", [0, 0, 9, 9])]:
        (tmp_path / "config" / f"{name}.json").write_text(json.dumps({"bbox_wgs84": bbox}))
    monkeypatch.setattr(refs, "REPO_ROOT", tmp_path)
    assert refs.mapped_areas() == {"south_lidar": [1, 2, 3, 4], "west_north": [5, 6, 7, 8]}


def test_mapped_areas_fall_back_to_map_json(tmp_path, monkeypatch):
    (tmp_path / "output" / "philly" / "tiles" / "v18").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "output" / "philly" / "tiles" / "v18" / "map.json").write_text(
        json.dumps({"areas": [{"area": "southwest", "label": "x", "cells": 1}]}))
    (tmp_path / "config" / "southwest.json").write_text(json.dumps({"bbox_wgs84": [1, 2, 3, 4]}))
    monkeypatch.setattr(refs, "REPO_ROOT", tmp_path)
    assert refs.mapped_areas() == {"southwest": [1, 2, 3, 4]}


@pytest.mark.skipif(not (REPO_ROOT / "output" / "philly" / "FROZEN_v18.json").exists(),
                    reason="output/ is git-ignored; needs the local v18 build")
def test_mapped_areas_real_repo():
    areas = refs.mapped_areas()
    assert list(areas) == V18_REGIONS
    assert "downtown_lidar" not in areas
    assert all(len(b) == 4 and b[0] < b[2] and b[1] < b[3] for b in areas.values())


# False matches found in the first real run (Nov. 26, 2026)

def test_single_word_alias_needs_the_whole_phrase():
    names = ["Merchants' Exchange Building", "Philadelphia Exchange"]
    assert refs.match_kind("Commercial Exchange, 135 South Second Street, Philadelphia, Philadelphia County, PA",
                           names, "143 S 3RD ST") is None
    assert refs.match_kind("Philadelphia Exchange Company, 143 South Third Street, Philadelphia, "
                           "Philadelphia County, PA", names, "143 S 3RD ST") == "clear"


def test_numbered_part_is_not_an_address():
    names = ["Philadelphia Naval Shipyard", "Philadelphia Navy Yard"]
    t = ("Naval Base Philadelphia-Philadelphia Naval Shipyard, 350-Ton Hammerhead Crane, League Island, "
         "Philadelphia, Philadelphia County, PA")
    assert refs.match_kind(t, names) == "uncertain"
    assert refs.match_kind("Christ Church, 22-26 North Second Street, Philadelphia, Philadelphia County, PA",
                           ["Christ Church"], "20 N AMERICAN ST") == "clear"


def test_comma_alias_matches_leading_segments():
    names = ["College Hall", "University of Pennsylvania, College Hall"]
    t = "University of Pennsylvania, College Hall, Woodland Avenue, Philadelphia, Philadelphia County, PA"
    assert refs.match_kind(t, names) == "clear"
    # a different hall at Penn is still not College Hall
    assert refs.match_kind("University of Pennsylvania, Houston Hall, Spruce Street, Philadelphia, "
                           "Philadelphia County, PA", names) is None


def test_parentheses_in_titles_do_not_block_a_phrase():
    assert refs.match_kind("Gloria Dei (Church), 929 South Water Street, Philadelphia, Philadelphia County, PA",
                           ["Gloria Dei (Old Swedes') Church", "Gloria Dei Church"], "916 S SWANSON ST") == "clear"
    assert refs.match_kind("Gloria Dei (Church), Rectory, 929 South Water Street, Philadelphia, "
                           "Philadelphia County, PA", ["Gloria Dei Church"], "916 S SWANSON ST") == "uncertain"


@pytest.mark.parametrize("caption,want", [
    ("1. North front - Carpenters' Company Hall, 320 Chestnut Street, Philadelphia, PA", "North front"),
    ("1-1 Title sheet - Christ Church, 22-26 North Second Street, Philadelphia, PA", "Title sheet"),
    ("0. Cover sheet - Second Bank of the United States, 420 Chestnut Street, Philadelphia, PA", "Cover sheet"),
    ("HABS PA,51-PHILA,6- (sheet 1 of 45) - Independence Hall Complex, Philadelphia, PA", None),
])
def test_sheet_title(caption, want):
    assert refs.sheet_title(caption) == want


# --- Index-driven targets, bridges and data pages (Nov. 26, 2026, step 1 follow-up) ---

def test_data_pages_are_listed(fake_loc):
    item = refs.loc_drawings("pa9999")
    assert item["data_pages"] == [{"kind": "data", "url": "https://tile.loc.gov/x/pa9999data.pdf"}]
    assert all("pdf" not in s["image_url"] for s in item["sheets"])


@pytest.mark.parametrize("title,names,want", [
    # railroad-led HAER title: the bridge's own name is the second segment
    ("Connecting Railway, Schuylkill River Bridge, Spanning Schuylkill River, north of Girard Avenue Bridge, "
     "Philadelphia, Philadelphia County, PA", ["Connecting Railway Bridge"], "clear"),
    ("Philadelphia & Reading Railroad, Columbia Bridge, Spanning Schuylkill River, Philadelphia, "
     "Philadelphia County, PA", ["Columbia Railroad Bridge"], "clear"),
    # "Spanning ... River" is a location
    ("Falls Bridge, Spanning Schuylkill River, connecting East & West River Drives, Philadelphia, "
     "Philadelphia County, PA", ["Falls Bridge"], "clear"),
    # a bridge named only as a landmark nearby
    ("Connecting Railway, Schuylkill River Bridge, Spanning Schuylkill River, north of Girard Avenue Bridge, "
     "Philadelphia, Philadelphia County, PA", ["Girard Avenue Bridge"], "uncertain"),
    # a different railroad bridge
    ("Pennsylvania Railroad, Manayunk Bridge, Spanning Schuylkill River & Green Lane, Philadelphia, "
     "Philadelphia County, PA", ["Falls Bridge"], None),
])
def test_bridge_titles(title, names, want):
    assert refs.match_kind(title, names) == want


def test_targets_come_from_the_index(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"entries": [
        {"slug": "city_hall", "name": "Philadelphia City Hall", "wikidata": "Q1138183"},
        {"slug": "falls_bridge", "name": "Falls Bridge", "wikidata": "Q5432461"},
        {"slug": "connecting_railroad_bridge", "name": "Connecting Railway Bridge over the Schuylkill",
         "wikidata": None},
    ]}))
    t = refs.drawing_targets(index)
    assert [x["slug"] for x in t] == ["city_hall", "falls_bridge", "connecting_railroad_bridge"]
    # manifest landmarks keep their LoC items and AIS address from LANDMARKS
    assert t[0]["loc_ids"] == ["pa4092"] and t[0]["address"] == "1400 JOHN F KENNEDY BLVD"
    assert t[1]["loc_ids"] == [] and t[1]["address"] is None
    assert t[2]["wikidata"] is None


def test_targets_fall_back_to_landmarks_without_index(tmp_path):
    t = refs.drawing_targets(tmp_path / "missing.json")
    assert [x["slug"] for x in t] == [s for s, *_ in refs.LANDMARKS]


def test_structures_not_being_modeled_are_skipped(tmp_path):
    """kit "suspension" (Ben Franklin and Walt Whitman, done in v18) and
    "context" are not modeled (scripts/49_landmark_index.py), so no search."""
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"entries": [
        {"slug": "city_hall", "name": "Philadelphia City Hall", "wikidata": "Q1138183", "kit": "mansard_tower"},
        {"slug": "ben_franklin_bridge", "name": "Benjamin Franklin Bridge", "wikidata": "Q817485",
         "kit": "suspension"},
        {"slug": "hagan_arena", "name": "Hagan Arena", "wikidata": "Q5638522", "kit": "context"},
    ]}))
    assert [x["slug"] for x in refs.drawing_targets(index)] == ["city_hall"]


def test_photo_counts_are_recorded(fake_loc, monkeypatch):
    assert refs.loc_drawings("pa9999")["photos_in_metadata"] == 1
    monkeypatch.setattr(refs, "get_json", lambda url, kind, post=None: {"results": [
        _result("pa0001", "Rodin Museum, 2151 Benjamin Franklin Parkway, Philadelphia, Philadelphia County, PA",
                "Photo(s): 19 | Color Transparencies: 3 | Data Page(s): 14")]})
    clear, _, _ = refs.loc_search("rodin_museum", "Rodin Museum", None)
    assert clear[0]["photos_in_metadata"] == 19 and clear[0]["drawings_in_metadata"] == 0


# Wrong bridge matches from the bridge run (Nov. 26, 2026)

@pytest.mark.parametrize("title,names,want", [
    # Reading, Berks County: "Philadelphia" only in the railroad's name
    ("Philadelphia & Reading Railroad, Walnut Street Bridge, Spanning Reading main line at Walnut Street, "
     "Reading, Berks County, PA", ["Walnut Street Bridge"], None),
    # Walnut Lane is not Walnut Street
    ("Walnut Lane Bridge, Spanning Lincoln Drive & Monoshone Creek at Walnut Lane, Philadelphia, "
     "Philadelphia County, PA", ["Walnut Street Bridge"], None),
    # a railroad bridge "at West Falls" is not the Falls Bridge
    ("Philadelphia & Reading Railroad, Bridge at West Falls, Spanning Schuylkill River, Philadelphia, "
     "Philadelphia County, PA", ["Falls Bridge"], "uncertain"),
    ("Chestnut Street Bridge, Schuykill River, Chestnut Street vicinity, Philadelphia, Philadelphia County, PA",
     ["Chestnut Street Bridge"], "clear"),
])
def test_wrong_bridge_matches(title, names, want):
    assert refs.match_kind(title, names) == want
