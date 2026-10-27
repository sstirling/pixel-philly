"""Property-record facades: the OPA fetch's PII guard, the join, and the
facade spec mapped from real OPA strings."""

import pytest
from shapely.geometry import Point, box

from pixelphilly import facades
from pixelphilly.opa import FORBIDDEN_PATTERNS, OPA_COLUMNS, PWD_COLUMNS, assert_no_pii, check_columns, opa_sql, pwd_sql

BBOX = [-75.150, 39.948, -75.140, 39.952]


# --- PII guard ---------------------------------------------------------------

@pytest.mark.parametrize("col", ["owner_1", "owner_2", "mailing_street", "mailing_address_1", "sale_price", "sale_date",
                                 "taxable_land", "exempt_building", "market_value", "homestead_exemption",
                                 "exterior_condition", "book_and_page", "registry_number", "cross_reference",
                                 "recording_date", "OWNER_1"])
def test_forbidden_columns_are_refused(col):
    with pytest.raises(ValueError, match="forbidden"):
        check_columns(["parcel_number", col])


def test_the_fetch_requests_only_explicit_allowed_columns():
    check_columns(OPA_COLUMNS)
    check_columns(PWD_COLUMNS)
    assert PWD_COLUMNS == ["parcelid", "brt_id"]
    for sql in (opa_sql(BBOX), pwd_sql(BBOX)):
        assert "*" not in sql.split("FROM")[0], "never SELECT *"
        lowered = sql.lower()
        assert not any(p.rstrip("*") in lowered for p in FORBIDDEN_PATTERNS if p != "market_value"), sql
        assert "market_value" not in lowered and "exterior_condition" not in lowered


def test_a_raw_file_with_pii_is_rejected():
    ok = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None,
                                                     "properties": {"parcel_number": "1", "location": "1 A ST"}}]}
    assert_no_pii(ok)
    bad = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None,
                                                      "properties": {"parcel_number": "1", "owner_1": "SMITH"}}]}
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_pii(bad)


# --- parsing real OPA strings --------------------------------------------------

@pytest.mark.parametrize("desc,kind,stories,material", [
    ("ROW 2 STY MASONRY", "row", 2, "brick"),
    ("ROW B/GAR 2 STY MASONRY", "row", 2, "brick"),
    ("SEMI/DET 2 STY MASONRY", "twin", 2, "brick"),
    ("APT 2-4 UNITS 2 STY MASON", "apartment", 2, "brick"),
    ("IND WAREHOUSE MASONRY", "industrial", None, "brick"),
    ("OFF BLD N/COM W/PKG MASON", "office", None, "brick"),
    ("DET W/GAR 2 STY FRAME", "detached", 2, "frame"),
    ("ROW 3 STY MAS+OTHER", "row", 3, "brick"),
    ("DET 2 STY STONE", "detached", 2, "stone"),
    ("IND WAREHOUSE METAL", "industrial", None, "metal"),
])
def test_building_code_description_is_parsed(desc, kind, stories, material):
    assert facades.parse_building_code(desc) == (kind, stories, material)


@pytest.mark.parametrize("new,old,category,style", [
    ("ROW PORCH FRONT", "ROW 2 STY MASONRY", "SINGLE FAMILY", "row_porch"),
    ("ROW TYPICAL", "ROW 2 STY MASONRY", "SINGLE FAMILY", "row_typical"),
    ("ROW OLD STYLE", "ROW 3 STY MASONRY", "SINGLE FAMILY", "row_typical"),
    ("ROW POST WAR", "ROW B/GAR 2 STY MASONRY", "SINGLE FAMILY", "row_postwar"),
    ("ROW MODERN", "ROW 3 STY MASONRY", "SINGLE FAMILY", "row_modern"),
    ("ROW RIVER ROW", "ROW 2 STY MASONRY", "SINGLE FAMILY", "river_row"),
    ("TWIN CONVENTIONAL", "SEMI/DET 2 STY MASONRY", "SINGLE FAMILY", "twin"),
    ("TWIN POST WAR", "SEMI/DET 2 STY MASONRY", "SINGLE FAMILY", "twin"),
    ("TWIN RANCH", "SEMI/DET 1 STY MASONRY", "SINGLE FAMILY", "twin"),
    ("ROW MIXED-COM/RES", "ROW CONV/APT 3 STY MASON", "MIXED USE", "mixed_storefront"),
    ("APARTMENTS - LOW RISE", "APT 2-4 UNITS 2 STY MASON", "MULTI FAMILY", "apartment_low"),
    ("WAREHOUSE", "IND WAREHOUSE MASONRY", "INDUSTRIAL", "warehouse"),
    ("DOWNTOWN ROW TYPE", "ROW 4 STY MASONRY", "COMMERCIAL", "row_typical"),
    ("RELIGIOUS", "CHURCH MASONRY", "COMMERCIAL", "institutional"),
    ("OFFICE BLDNG - High Rise", "OFF BLD N/COM W/PKG MASON", "COMMERCIAL", "office_tower"),
    (None, "DET W/GAR 2 STY FRAME", "SINGLE FAMILY", "detached"),
    (None, "ROW 2 STY MASONRY", "SINGLE FAMILY", "row_typical"),  # codes 41-47: no new description
    (None, None, None, "other"),
])
def test_style_from_real_codes(new, old, category, style):
    rec = {"building_code_description_new": new, "building_code_description": old,
           "category_code_description": category}
    assert facades.style_of(rec, height_m=10.0) == style


def test_facade_spec_fields():
    rec = {"building_code_description_new": "ROW PORCH FRONT", "building_code_description": "ROW 2 STY MASONRY",
           "category_code_description": "SINGLE FAMILY", "number_stories": 2, "year_built": "1925",
           "general_construction": "A"}
    s = facades.facade_spec(rec, 8.4, box(0, 0, 5, 15), "123")
    assert (s["style"], s["material"], s["stories"]) == ("row_porch", "brick", 2)
    assert s["floor_h"] == pytest.approx(4.2)
    assert s["porch"] and s["cornice"] and not s["storefront"]
    assert all(0 <= c <= 255 for c in s["wall_rgb"] + s["window_rgb"])
    # Stories from height when the record has none (or none at all)
    s2 = facades.facade_spec({**rec, "number_stories": None}, 9.6, box(0, 0, 5, 15), "123")
    assert s2["stories"] == 3 and s2["floor_h"] == pytest.approx(3.2)


def test_mixed_use_gets_a_storefront_and_towers_get_glass():
    mixed = {"building_code_description_new": "ROW MIXED-COM/RES", "building_code_description": "ROW CONV/APT 3 STY MASON",
             "category_code_description": "MIXED USE", "number_stories": 3}
    assert facades.facade_spec(mixed, 11.0, box(0, 0, 6, 18), "1")["storefront"]
    tower = {"building_code_description_new": "OFFICE BLDNG - High Rise", "building_code_description": "OFF BLD N/COM W/PKG MASON",
             "category_code_description": "COMMERCIAL", "number_stories": None, "year_built": "1987"}
    spec = facades.facade_spec(tower, 150.0, box(0, 0, 40, 40), "2")
    assert spec["style"] == "office_tower" and spec["material"] == "glass"
    # An old masonry high-rise stays masonry
    old = {**tower, "year_built": "1931"}
    assert facades.facade_spec(old, 150.0, box(0, 0, 40, 40), "3")["material"] == "brick"


def test_general_construction_is_only_a_weak_fallback():
    rec = {"building_code_description": "STORE 1 STY", "general_construction": "C"}
    assert facades.facade_spec(rec, 4.0, box(0, 0, 8, 10), "1")["material"] == "frame"
    rec = {"building_code_description": "ROW 2 STY MASONRY", "general_construction": "C"}
    assert facades.facade_spec(rec, 8.0, box(0, 0, 5, 15), "1")["material"] == "brick", "the code's material wins"


def test_color_jitter_is_deterministic_per_building():
    rec = {"building_code_description": "ROW 2 STY MASONRY", "building_code_description_new": "ROW TYPICAL"}
    a = facades.facade_spec(rec, 8.0, box(0, 0, 5, 15), "4410")
    b = facades.facade_spec(rec, 8.0, box(0, 0, 5, 15), "4410")
    c = facades.facade_spec(rec, 8.0, box(0, 0, 5, 15), "4411")
    assert a["wall_rgb"] == b["wall_rgb"]
    assert a["wall_rgb"] != c["wall_rgb"], "neighbors in a row differ slightly"
    assert max(abs(x - y) for x, y in zip(a["wall_rgb"], c["wall_rgb"])) <= 40


def test_typology_default_for_unmatched_footprints():
    narrow = facades.facade_spec(None, 9.0, box(0, 0, 5, 16), "1")
    assert narrow["style"] == "row_typical" and narrow["material"] == "brick"
    assert facades.facade_spec(None, 9.0, box(0, 0, 80, 60), "1")["style"] == "warehouse"
    assert facades.facade_spec(None, 80.0, box(0, 0, 40, 40), "1")["style"] == "office_tower"


def test_compact_is_small_and_complete():
    spec = facades.facade_spec(None, 9.0, box(0, 0, 5, 16), "1")
    c = facades.compact(spec)
    assert set(c) == {"s", "w", "g", "f", "p", "b"}
    assert c["s"] == facades.STYLE_IDS["row_typical"]
    assert c["b"] & facades.BAND_CORNICE and not c["b"] & facades.BAND_STOREFRONT


# --- join --------------------------------------------------------------------

def _opa(parcel, location, new, x, y, old="ROW 2 STY MASONRY"):
    return {"parcel_number": parcel, "location": location, "building_code_description_new": new,
            "building_code_description": old, "_pt": Point(x, y)}


def test_join_precedence_parcel_then_address_then_point():
    fps = [
        {"id": 1, "parcel_id_num": "10", "address": "1 A ST", "geom": box(0, 0, 5, 15)},
        {"id": 2, "parcel_id_num": "99", "address": "3 A ST", "geom": box(5, 0, 10, 15)},  # no PWD parcel 99
        {"id": 3, "parcel_id_num": None, "address": "UNKNOWN", "geom": box(10, 0, 15, 15)},
        {"id": 4, "parcel_id_num": None, "address": None, "geom": box(100, 100, 110, 110)},
    ]
    pwd = {"10": "100000001"}
    opa = [
        _opa("100000001", "1 A ST", "ROW TYPICAL", 50, 50),  # parcel match, even though its point is elsewhere
        _opa("100000002", "1 A ST", "ROW PORCH FRONT", 2, 2),  # same address, lower precedence
        _opa("100000003", "3 A ST", "ROW POST WAR", 50, 50),  # address match for footprint 2
        _opa("100000004", "5 A ST", "TWIN CONVENTIONAL", 12, 5),  # inside footprint 3
    ]
    res = facades.join(fps, opa, pwd)
    assert res[1][1] == "parcel" and res[1][0]["building_code_description_new"] == "ROW TYPICAL"
    assert res[2][1] == "address" and res[2][0]["building_code_description_new"] == "ROW POST WAR"
    assert res[3][1] == "point" and res[3][0]["building_code_description_new"] == "TWIN CONVENTIONAL"
    assert res[4] == (None, None)


def test_condo_address_duplicates_take_the_majority_style():
    fps = [{"id": 1, "parcel_id_num": None, "address": "200 N 3RD ST", "geom": box(0, 0, 20, 20)}]
    opa = [_opa(f"88800{i}", "200 N 3RD ST", "APARTMENTS - LOW RISE", 50, 50, "APT 2-4 UNITS 2 STY MASON")
           for i in range(3)] + [_opa("888009", "200 N 3RD ST", "ROW MIXED-COM/RES", 50, 50)]
    rec, how = facades.join(fps, opa, {})[1]
    assert how == "address" and rec["building_code_description_new"] == "APARTMENTS - LOW RISE"


def test_address_ranges_match_their_first_number():
    fps = [{"id": 1, "parcel_id_num": None, "address": "100-16 S INDEPENDENCE MALL W", "geom": box(0, 0, 20, 20)}]
    opa = [_opa("1", "100 S INDEPENDENCE MALL W", "OFFICE BLDNG - High Rise", 50, 50)]
    assert facades.join(fps, opa, {})[1][1] == "address"


@pytest.mark.parametrize("old,height,style", [
    ("RES CONDO 4 STY MASONRY", 14.0, "apartment_low"),
    ("RES CONDO 5+ STY MASONRY", 30.0, "apartment_low"),
    ("RES CONDO 5+ STY MAS+OTH", 120.0, "office_tower"),
])
def test_condos_are_apartments_or_towers(old, height, style):
    # Downtown: most records with no new code are condos (3,234 "RES CONDO 5+
    # STY MASONRY" rows near Independence Hall), and fell through to "other"
    assert facades.style_of({"building_code_description": old}, height) == style
    assert facades.parse_building_code(old)[2] == "brick"


# --- street-facing walls -------------------------------------------------------

def test_front_is_the_wall_facing_the_street():
    from shapely.geometry import LineString

    lot = box(0, 0, 5, 15)  # a rowhouse lot, street along its south (short) side
    street = LineString([(-50, -6), (50, -6)])
    dirs = facades.front_dirs(lot, [street])
    assert len(dirs) == 1 and dirs[0] == pytest.approx((0.0, -1.0), abs=1e-6)
    # An alley behind isn't in the street layer, so the back isn't a front
    corner = facades.front_dirs(box(0, 0, 5, 15), [street, LineString([(11, -50), (11, 50)])])
    assert len(corner) == 2 and (1.0, 0.0) in [tuple(round(v, 6) for v in d) for d in corner]
    assert facades.front_dirs(lot, []) == []
    assert facades.front_dirs(lot, [LineString([(500, 500), (600, 500)])]) == [], "no street nearby"


# --- OSM tags (track 2) ----------------------------------------------------------

@pytest.mark.parametrize("value,rgb", [
    ("#b05030", (176, 80, 48)), ("#fff", (255, 255, 255)), ("tan", (210, 180, 140)), ("Beige", (245, 245, 220)),
    ("light grey", None), ("", None), (None, None), ("#12345", None),
])
def test_osm_colour_parsing(value, rgb):
    assert facades.parse_colour(value) == rgb


@pytest.mark.parametrize("tag,material", [("brick", "brick"), ("stone", "stone"), ("limestone", "stone"),
                                          ("sandstone", "stone"), ("concrete", "stone"), ("glass", "glass"),
                                          ("metal", "metal"), ("wood", "frame"), ("plaster", "stone"), ("vinyl", None)])
def test_osm_material_mapping(tag, material):
    assert facades.osm_material(tag) == material


def _osm(geom, tags, part=False):
    return {"geom": geom, "tags": tags, "part": part}


def test_osm_precedence_part_then_building_then_opa():
    rec = {"building_code_description": "OFF BLD N/COM W/PKG MASON", "building_code_description_new": "OFFICE BLDNG - High Rise",
           "year_built": "1931"}
    tower = box(0, 0, 40, 40)
    building = _osm(box(0, 0, 40, 40), {"building": "yes", "building:colour": "#c8b89a"})
    part = _osm(box(10, 10, 30, 30), {"building:part": "yes", "building:colour": "#203040"}, part=True)
    # The whole tower: the building's colour
    spec = facades.facade_spec(rec, 150.0, tower, "1", osm=facades.osm_match(tower, [building, part]))
    assert spec["wall_rgb"] == [200, 184, 154] and spec["color_source"] == "osm"
    # Its top part (a LiDAR part matching the OSM part): the part's colour
    top = box(11, 11, 29, 29)
    spec = facades.facade_spec(rec, 150.0, top, "1", osm=facades.osm_match(top, [building, part]))
    assert spec["wall_rgb"] == [32, 48, 64]
    # Material only: the material's palette, no roof sampling
    stone = _osm(box(0, 0, 40, 40), {"building": "yes", "building:material": "limestone"})
    spec = facades.facade_spec(rec, 150.0, tower, "1", osm=facades.osm_match(tower, [stone]))
    assert spec["material"] == "stone" and not spec["roof_color"]
    # A small overlap doesn't count
    assert facades.osm_match(tower, [_osm(box(35, 35, 60, 60), {"building:colour": "red"})]) == {}


@pytest.mark.parametrize("old,new,height,stories,roof", [
    ("OFF BLD N/COM W/PKG MASON", "OFFICE BLDNG - High Rise", 150.0, None, True),  # pale stone towers stay pale
    ("RES CONDO 5+ STY MASONRY", None, 40.0, None, True),
    ("APT 2-4 UNITS 2 STY MASON", "APARTMENTS - LOW RISE", 8.0, 2, False),  # low: brick is right
    ("ROW CONV/APT 3 STY MASON", "ROW MIXED-COM/RES", 11.0, 3, False),
    ("ROW CONV/APT 3 STY MASON", "ROW MIXED-COM/RES", 24.0, 6, True),
    ("ROW 4 STY MASONRY", "DOWNTOWN ROW TYPE", 22.0, 4, False),  # rowhouse styles keep brick
])
def test_tall_masonry_buildings_take_their_own_aerial_color(old, new, height, stories, roof):
    # OPA's "MASONRY" covers limestone and terra cotta as well as brick; at
    # City Hall pale towers turned red. Non-rowhouse buildings above 20 m or 4
    # floors with no OSM colour use their own roof colour from the aerial
    rec = {"building_code_description": old, "building_code_description_new": new, "number_stories": stories,
           "year_built": "1930"}
    spec = facades.facade_spec(rec, height, box(0, 0, 30, 30), "1")
    assert spec["roof_color"] is roof
    assert ("u" in facades.compact(spec)) is roof


def test_compact_carries_front_directions():
    spec = facades.facade_spec(None, 9.0, box(0, 0, 5, 16), "1")
    assert "d" not in facades.compact(spec)
    c = facades.compact({**spec, "front": [(0.0, -1.0), (1.0, 0.0)]})
    assert c["d"] == [0.0, -1.0, 1.0, 0.0]
    assert facades.compact({**spec, "front": [(0.0, -1.0)]})["d"] == [0.0, -1.0, 0.0, 0.0]


# --- glass only on evidence -------------------------------------------------------
# Real OPA rows, copied from data/raw/atlas_cityhall_fac_opa.geojson (Oct. 25)
CITY_HALL = {"location": "1400 JOHN F KENNEDY BLVD", "category_code_description": "COMMERCIAL",
             "building_code_description": "OFF BLD N/PKG N/COM MASON",
             "building_code_description_new": "GOV'T MUNICIPAL/STATE/FEDERAL", "year_built": "2015",
             "year_built_estimate": None, "number_stories": None}
COMCAST_CENTER = {"location": "1701 JOHN F KENNEDY BLVD", "category_code_description": "OFFICES",
                  "building_code_description": "OFF BLD N/COM W/PKG MASON",
                  "building_code_description_new": "OFFICE BLDNG - High Rise", "year_built": "2007",
                  "year_built_estimate": None, "number_stories": 58}
ACADEMY_HOUSE = {"location": "1500-14 LOCUST ST", "category_code_description": "MULTI FAMILY",
                 "building_code_description": "APTS 100+ UNITS MASONRY",
                 "building_code_description_new": "APTS - HIGH RISE", "year_built": "1972",
                 "year_built_estimate": None, "number_stories": 45}


def test_city_hall_is_not_glass():
    # OPA gives City Hall year_built 2015; it's a government building in stone
    spec = facades.facade_spec(CITY_HALL, 167.0, box(0, 0, 150, 140), "489522")
    assert spec["material"] != "glass" and not spec["glass"]
    assert spec["style"] == "institutional" and spec["roof_color"], "its own aerial colour"


def test_comcast_center_is_glass():
    spec = facades.facade_spec(COMCAST_CENTER, 297.0, box(0, 0, 60, 60), "1")
    assert spec["material"] == "glass" and spec["glass"]


@pytest.mark.parametrize("rec,why", [
    (ACADEMY_HOUSE, "an apartment tower from 1972"),
    ({**COMCAST_CENTER, "year_built": "1965", "year_built_estimate": "Y"}, "an estimated 1960s year"),
    ({**COMCAST_CENTER, "year_built": "1968"}, "before 1975"),
    ({**COMCAST_CENTER, "year_built_estimate": "Y"}, "an estimated year"),
    ({**COMCAST_CENTER, "category_code_description": "GOVERNMENT"}, "a government building"),
    ({**COMCAST_CENTER, "building_code_description_new": "HOTEL - HI RISE"}, "not an office building"),
])
def test_no_glass_without_evidence(rec, why):
    spec = facades.facade_spec(rec, 150.0, box(0, 0, 40, 40), "1")
    assert spec["material"] != "glass", why
    assert spec["roof_color"], why  # falls through to the tall-building rule


def test_short_modern_office_is_not_glass():
    assert facades.facade_spec(COMCAST_CENTER, 30.0, box(0, 0, 40, 40), "1")["material"] != "glass"


def test_osm_glass_overrides():
    m = facades.osm_match(box(0, 0, 40, 40), [{"geom": box(0, 0, 40, 40), "tags": {"building:material": "glass"},
                                               "part": False}])
    spec = facades.facade_spec(ACADEMY_HOUSE, 150.0, box(0, 0, 40, 40), "1", osm=m)
    assert spec["material"] == "glass" and spec["glass"]
    blue = facades.osm_match(box(0, 0, 40, 40), [{"geom": box(0, 0, 40, 40), "tags": {"building:colour": "#4a6f8a"},
                                                  "part": False}])
    assert facades.facade_spec(ACADEMY_HOUSE, 150.0, box(0, 0, 40, 40), "1", osm=blue)["glass"]
    tan = facades.osm_match(box(0, 0, 40, 40), [{"geom": box(0, 0, 40, 40), "tags": {"building:colour": "tan"},
                                                 "part": False}])
    assert not facades.facade_spec(COMCAST_CENTER, 297.0, box(0, 0, 40, 40), "1", osm=tan)["glass"]


def test_unmatched_tall_footprints_are_not_assumed_glass():
    spec = facades.facade_spec(None, 80.0, box(0, 0, 40, 40), "1")
    assert spec["material"] != "glass" and spec["roof_color"]


def test_mid_rise_offices_are_not_glass():
    # 1625 Chestnut St: "OFFICE BLDNG - Mid Rise", 1990, 57 m; masonry
    rec = {**COMCAST_CENTER, "location": "1625 CHESTNUT ST", "building_code_description_new": "OFFICE BLDNG - Mid Rise",
           "year_built": "1990", "number_stories": None}
    assert facades.facade_spec(rec, 57.3, box(0, 0, 40, 40), "70278")["material"] != "glass"


def test_osm_match_with_a_spatial_index_gives_the_same_result():
    # South Philly: 873 OSM shapes x ~116k footprints and ~233k LiDAR parts
    # took hours without an index
    import random

    from shapely import STRtree

    rng = random.Random(0)
    items = []
    for i in range(300):
        x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
        tags = {"building:colour": rng.choice(["#c8b89a", "tan", "#203040"])} if i % 2 else {"building:material": "brick"}
        items.append({"geom": box(x, y, x + rng.uniform(5, 60), y + rng.uniform(5, 60)), "tags": tags,
                      "part": rng.random() < 0.3})
    index = facades.osm_index(items)
    assert isinstance(index["tree"], STRtree)
    for _ in range(400):
        x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
        g = box(x, y, x + rng.uniform(4, 50), y + rng.uniform(4, 50))
        assert facades.osm_match(g, items) == facades.osm_match(g, index)
