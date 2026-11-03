"""Needle scan: small parts far taller than everything around them."""

from pixelphilly.qa_scan import find_needles


def rect(pid, x0, y0, x1, y1, h):
    return {"id": pid, "h": h, "polys": [[[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]]}


def test_needle_on_a_low_roof_is_found():
    # The City Hall wing cluster: ~9 m² at 145 m beside a 48 m roof
    parts = [rect("1-0", 0, 0, 40, 40, 48.0), rect("1-1", 40, 10, 43, 13, 145.7)]
    hits = find_needles(parts)
    assert [h["id"] for h in hits] == ["1-1"]
    assert hits[0]["neighbor_max_m"] == 48.0


def test_tower_top_and_statue_are_not_needles():
    # William Penn: a small part 17 m above the tower top beside it
    parts = [rect("2-0", 0, 0, 30, 30, 150.0), rect("2-1", 30, 14, 32, 16, 166.8)]
    assert find_needles(parts) == []


def test_large_or_low_parts_are_ignored():
    parts = [
        rect("3-0", 0, 0, 40, 40, 10.0),
        rect("3-1", 40, 0, 50, 10, 90.0),  # 100 m²: a real tower, not a needle
        rect("3-2", 60, 0, 62, 2, 30.0),  # isolated but under 40 m tall
    ]
    assert find_needles(parts) == []


def test_isolated_tall_sliver_with_no_neighbors_is_found():
    parts = [rect("4-0", 0, 0, 2, 2, 60.0)]
    assert [h["id"] for h in find_needles(parts)] == ["4-0"]


def test_footprint_id_of_parts_whole_buildings_and_structures():
    # Whole (unshaped) buildings keep the City's integer objectid; LiDAR parts
    # are "<objectid>-<part>" and structures "s<region>-<part>"
    # (east_riverfront's first scan crashed on an int id, Nov. 2)
    from pixelphilly.qa_scan import footprint_id

    assert footprint_id(310603) == "310603"
    assert footprint_id("310603-9") == "310603"
    assert footprint_id("s1459-0") == "s1459"
