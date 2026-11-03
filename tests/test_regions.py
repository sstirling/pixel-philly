"""Known-band helpers for drawing a region next to one already drawn."""

import numpy as np
import pytest

from pixelphilly.projection import Frame
from pixelphilly.regions import known_mask, near_known, rebase, shared_frames


def _f(col, row, name=None):
    return {"name": name or f"f{col}{row}", "col": col, "row": row}


def test_known_mask_is_one_on_known_ramps_then_zero():
    cell, ramp = 16, 8
    # Three frames in a row: known, new, new
    frames = [_f(0, 0, "k"), _f(1, 0, "a"), _f(2, 0, "b")]
    m = known_mask(frames, {"k"}, cell, ramp)
    assert m.shape == (cell, 3 * cell)
    assert m.dtype == np.float32
    assert np.all(m[:, :cell] == 1.0)
    # Ramp: d = 1..ramp cells past the band edge
    for d in range(1, ramp + 1):
        assert m[0, cell - 1 + d] == pytest.approx(1 - d / (ramp + 1))
    assert np.all(m[:, cell + ramp:] == 0.0)
    # Strictly decreasing across the ramp
    row = m[0, cell - 1:cell + ramp + 1]
    assert np.all(np.diff(row) < 0)


def test_known_mask_is_zero_off_frames_and_without_known():
    cell = 8
    # An L of frames: (0,0) known, (1,0) new; (0,1) and (1,1) are not frames
    frames = [_f(0, 0, "k"), _f(1, 0, "a"), _f(1, 1, "c")]
    m = known_mask(frames, {"k"}, cell, 4)
    assert np.all(m[cell:, :cell] == 0.0), "cells no frame covers stay 0"
    # Chebyshev: the diagonal frame's corner cell is within the ramp
    assert m[cell, cell] == pytest.approx(1 - 1 / 5)
    assert not known_mask(frames, set(), cell, 4).any()


def _frames(cols, rows, size=1024, c0=-3, r0=5):
    return [Frame(col=c, row=r, x0=(c + c0) * size, y0=(r + r0) * size, size=size)
            for r in range(rows) for c in range(cols)]


def test_shared_frames_match_by_screen_corner_not_name():
    north = _frames(4, 3)
    # South's lattice numbers frames from its own corner: same ground, other names
    south = [Frame(col=f.col + 10, row=f.row + 7, x0=f.x0, y0=f.y0, size=f.size) for f in north if f.row == 2]
    m = shared_frames(north, south)
    assert len(m) == 4
    assert m["frame_00_02"] == "frame_10_09"


def test_near_known_picks_a_small_boundary_patch():
    frames = _frames(6, 4)
    known = {f.name for f in frames if f.row == 3}  # bottom row is the band
    center = next(f for f in frames if f.name == "frame_02_03")
    sub = near_known(frames, known, 1, center=center)
    assert sorted(f.name for f in sub) == ["frame_01_02", "frame_01_03", "frame_02_02", "frame_02_03",
                                           "frame_03_02", "frame_03_03"]
    # Without a center: all new frames within 1 of the band, plus band frames next to them
    sub = near_known(frames, known, 1)
    assert {f.name for f in sub} == {f.name for f in frames if f.row >= 2}


def test_rebase_moves_the_subset_to_the_canvas_corner():
    sub = [f for f in _frames(6, 4) if f.col >= 2 and f.row >= 1]
    r = rebase(sub)
    assert min(f["col"] for f in r) == 0 and min(f["row"] for f in r) == 0
    assert {f["name"] for f in r} == {f.name for f in sub}


def test_repair_mask_strip_is_new_cells_near_known_only():
    from pixelphilly.regions import repair_mask

    cell, width = 16, 10
    frames = [_f(0, 0, "k"), _f(1, 0, "a"), _f(2, 0, "b"), _f(1, 1, "c")]
    fixed, strip = repair_mask(frames, {"k"}, cell, width)
    assert fixed.shape == strip.shape == (2 * cell, 3 * cell)
    assert fixed.dtype == np.float32 and strip.dtype == bool
    assert not strip[:cell, :cell].any(), "known cells are never in the strip"
    assert strip[:cell, cell:cell + width].all() and not strip[:, cell + width:].any()
    # The diagonal frame "c" is within Chebyshev reach of the known corner
    assert strip[cell, cell] and not strip[cell:, :cell].any(), "cells no frame covers aren't in it"
    assert np.array_equal(fixed, (~strip).astype(np.float32))
    assert not repair_mask(frames, set(), cell, width)[1].any()


def test_repair_step_picks_the_sigma_nearest_the_target():
    from pixelphilly.regions import repair_step

    assert repair_step([1.0, 0.9, 0.7, 0.55, 0.3, 0.0], 0.6) == 3
    assert repair_step([1.0, 0.0], 0.6) == 0


def test_union_lattice_first_area_wins_and_offsets_line_up():
    from pixelphilly.regions import union_lattice

    size = 1024
    # South: global cells (0..3, 2..4); North: (1..4, 0..2), overlapping on row 2
    south = [Frame(col=c, row=r - 2, x0=c * size, y0=r * size, size=size) for r in range(2, 5) for c in range(4)]
    north = [Frame(col=c - 1, row=r, x0=c * size, y0=r * size, size=size) for r in range(0, 3) for c in range(1, 5)]
    u = union_lattice([("south", south), ("north", north)])
    assert (u["cols"], u["rows"]) == (5, 5) and (u["x0"], u["y0"]) == (0, 0)
    # The shared row 2 (cells 1..3) keeps South; cell (4, 2) exists only in North
    assert all(u["cells"][(c, 2)][0] == "south" for c in range(4))
    assert u["cells"][(4, 2)][0] == "north"
    assert u["counts"] == {"south": 12, "north": 9}  # 12 North cells, 3 shared with South
    assert (0, 0) not in u["cells"], "cells neither area has stay empty"
    # Each cell's frame sits at the union offset of its global position
    for (c, r), (_, f) in u["cells"].items():
        assert (f.x0 - u["x0"], f.y0 - u["y0"]) == (c * size, r * size)


def test_check_same_space_refuses_mismatched_areas():
    from pixelphilly.projection import load_config
    from pixelphilly.regions import check_same_space

    south, north = load_config("south_lidar"), load_config("north_lidar")
    check_same_space([south, north])
    with pytest.raises(ValueError, match="projection origins"):
        check_same_space([south, {**north, "projection_origin": [-75.0, 39.9]}])
    with pytest.raises(ValueError, match="cameras"):
        check_same_space([south, {**north, "camera": {**north["camera"], "frame_px": 512}}])


def test_union_tiles_take_the_first_area_and_mask_empty_cells(tmp_path):
    # 16_build_tiles.py --areas: assembled with pyvips one PNG per cell; the
    # shared cell keeps the first area's pixels, cells no area has are masked
    import importlib.util

    from PIL import Image
    from shapely.geometry import box

    from pixelphilly.projection import REPO_ROOT
    from pixelphilly.regions import union_lattice

    spec = importlib.util.spec_from_file_location("build_tiles", REPO_ROOT / "scripts" / "16_build_tiles.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)

    size = 8
    south = [Frame(col=c, row=0, x0=c * size, y0=size, size=size) for c in range(2)]  # global row 1
    north = [Frame(col=c, row=0, x0=(c + 1) * size, y0=y * size, size=size) for y in (0, 1) for c in range(1)]
    colors = {"south": (200, 0, 0), "north": (0, 0, 200)}
    for area, frames in (("south", south), ("north", north)):
        for f in frames:
            Image.new("RGB", (size, size), colors[area]).save(tmp_path / f"{area}_{f.name}.png")
    u = union_lattice([("south", south), ("north", north)])
    img = bt.union_layer(u, size, lambda a, f: tmp_path / f"{a}_{f.name}.png")
    assert (img.width, img.height) == (2 * size, 2 * size)
    px = lambda x, y: tuple(int(v) for v in img.getpoint(x, y))  # noqa: E731
    assert px(12, 12) == colors["south"], "the shared cell (1, 1) keeps South"
    assert px(12, 4) == colors["north"] and px(4, 12) == colors["south"]
    mask = bt.union_mask(u, size)
    assert mask.getpoint(4, 4)[0] == 0 and mask.getpoint(12, 4)[0] == 255
    # Missing imagery over part of a cell is cut out of that cell only
    nodata = box(12, 12, 16, 16)
    m2 = bt.union_mask(u, size, nodata)
    assert m2.getpoint(14, 14)[0] == 0 and m2.getpoint(9, 9)[0] == 255


def test_union_sources_use_a_later_areas_band_override(tmp_path):
    # Base = the first area's finished frame; a later region run's
    # water_band/ repaint of a known-band frame replaces that cell
    import importlib.util
    import json

    from pixelphilly.projection import REPO_ROOT
    from pixelphilly.regions import union_lattice

    spec = importlib.util.spec_from_file_location("build_tiles", REPO_ROOT / "scripts" / "16_build_tiles.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)

    size = 8
    south = [Frame(col=c, row=0, x0=c * size, y0=size, size=size) for c in range(2)]
    north = [Frame(col=0, row=r, x0=size, y0=r * size, size=size) for r in range(2)]
    u = union_lattice([("south", south), ("north", north)])
    band = tmp_path / "output" / "north" / "postprocessed" / "p" / "water_band"
    band.mkdir(parents=True)
    (band / "report.json").write_text(json.dumps({"known_area": "south"}))
    (band / "frame_01_00.png").write_bytes(b"")  # South's frame at the shared cell
    src, overrides = bt.cell_sources(u, ["south", "north"], "p", "water", tmp_path)
    shared = next(c for c, (a, f) in u["cells"].items() if a == "south" and f.name == "frame_01_00")
    assert src[shared] == band / "frame_01_00.png" and overrides == {"north": 1}
    other = next(c for c, (a, f) in u["cells"].items() if a == "south" and f.name == "frame_00_00")
    assert src[other] == tmp_path / "output" / "south" / "postprocessed" / "p" / "water" / "frame_00_00.png"


# --- Several known areas (West Philly borders South and North) ---

def _three_areas(size=8):
    # Global lattice cells: South rows 2-3, cols 0-3; North rows 0-2, cols 1-3
    # (row 2 shared with South); West rows 1-3, cols 3-4 (shares (3,2) with
    # both, (3,1) with North, (3,3) with South)
    def lat(cells, c0, r0):
        return [Frame(col=c - c0, row=r - r0, x0=c * size, y0=r * size, size=size) for c, r in cells]

    south = lat([(c, r) for r in (2, 3) for c in range(4)], 0, 2)
    north = lat([(c, r) for r in range(3) for c in range(1, 4)], 1, 0)
    west = lat([(c, r) for r in range(1, 4) for c in (3, 4)], 3, 1)
    return south, north, west


def _band(root, area, prompt, owners):
    """A region run's water_band/: flat with known_area (one owner, North's
    layout) or per-owner subfolders (several)."""
    import json

    band = root / "output" / area / "postprocessed" / prompt / "water_band"
    band.mkdir(parents=True, exist_ok=True)
    if len(owners) == 1 and owners[0][0] == "flat":
        (band / "report.json").write_text(json.dumps({"known_area": owners[0][1]}))
        for name in owners[0][2]:
            (band / f"{name}.png").write_bytes(b"")
    else:
        (band / "report.json").write_text(json.dumps({"owners": [o for o, _ in owners]}))
        for owner, names in owners:
            (band / owner).mkdir(exist_ok=True)
            for name in names:
                (band / owner / f"{name}.png").write_bytes(b"")
    return band


def test_two_known_areas_first_listed_owns_a_shared_cell(tmp_path):
    from pixelphilly.regions import known_sources

    south, north, west = _three_areas()
    ks = known_sources(west, [("south", south), ("north", north)], "p", "water", tmp_path)
    by_pos = {(f.x0, f.y0): f.name for f in west}
    owner = {(f.x0 // 8, f.y0 // 8): ks[f.name][0] for f in west if f.name in ks}
    assert owner == {(3, 1): "north", (3, 2): "south", (3, 3): "south"}
    assert by_pos and all(ks[n][2].parent.name == "water" for n in ks)


def test_known_pixels_are_the_merged_map_pixels(tmp_path):
    # A South cell North re-repainted (water_band) must reach West as the
    # re-repainted file, exactly what the merged map uses
    from pixelphilly.regions import cell_sources, known_sources, union_lattice

    south, north, west = _three_areas()
    s32 = next(f for f in south if (f.x0, f.y0) == (24, 16))
    band = _band(tmp_path, "north", "p", [("flat", "south", [s32.name])])
    ks = known_sources(west, [("south", south), ("north", north)], "p", "water", tmp_path,
                       override_from=["south", "north", "west"])
    w32 = next(f for f in west if (f.x0, f.y0) == (24, 16))
    assert ks[w32.name] == ("south", s32.name, band / f"{s32.name}.png")
    u = union_lattice([("south", south), ("north", north), ("west", west)])
    src, _ = cell_sources(u, ["south", "north", "west"], "p", "water", tmp_path)
    for f in west:
        if f.name in ks:
            cell = ((f.x0 - u["x0"]) // 8, (f.y0 - u["y0"]) // 8)
            assert src[cell] == ks[f.name][2]


def test_union_of_three_areas_with_overrides_later_area_wins(tmp_path):
    from pixelphilly.regions import cell_sources, union_lattice

    south, north, west = _three_areas()
    s32 = next(f for f in south if (f.x0, f.y0) == (24, 16))
    n31 = next(f for f in north if (f.x0, f.y0) == (24, 8))
    _band(tmp_path, "north", "p", [("flat", "south", [s32.name])])
    wband = _band(tmp_path, "west", "p", [("south", [s32.name]), ("north", [n31.name])])
    u = union_lattice([("south", south), ("north", north), ("west", west)])
    src, overrides = cell_sources(u, ["south", "north", "west"], "p", "water", tmp_path)
    assert u["counts"] == {"south": 8, "north": 6, "west": 3}
    cell = lambda f: ((f.x0 - u["x0"]) // 8, (f.y0 - u["y0"]) // 8)  # noqa: E731
    assert src[cell(s32)] == wband / "south" / f"{s32.name}.png", "West's later re-repaint wins"
    assert src[cell(n31)] == wband / "north" / f"{n31.name}.png"
    assert overrides == {"north": 1, "west": 2}


def test_ripple_reference_is_the_root_of_the_known_chain():
    # South drawn alone; North next to South; West next to South and North.
    # Ripples placed in the root's (South's) mosaic coordinates give every
    # screen pixel the same ripple in all three
    from pixelphilly import waterpaint
    from pixelphilly.regions import mosaic_origin, ripple_offset, ripple_root

    south, north, west = _three_areas(size=64)
    chain = {"south": None, "north": ["south"], "west": ["south", "north"]}
    assert ripple_root("west", chain.get) == "south" and ripple_root("south", chain.get) == "south"
    x, y, w, h = 3 * 64 + 5, 2 * 64 + 7, 400, 300
    masks = []
    for frames in (south, north, west):
        ox, oy = ripple_offset(frames, south)
        mx, my = mosaic_origin(frames)
        masks.append(waterpaint.ripple_mask(w, h, x - mx + ox, y - my + oy))
    assert masks[0].any() and all(np.array_equal(masks[0], m) for m in masks[1:])


def test_owner_edges_lists_frame_borders_between_regions():
    from pixelphilly.regions import owner_edges

    # 3 x 2 union canvas: column 0 is A, columns 1-2 are B except (2, 1), which is C
    cells = {(0, 0): ("A", "a0"), (0, 1): ("A", "a1"), (1, 0): ("B", "b0"), (1, 1): ("B", "b1"),
             (2, 0): ("B", "b2"), (2, 1): ("C", "c0")}
    edges = owner_edges(cells)
    got = sorted((e["pair"], e["a"], e["b"], e["axis"]) for e in edges)
    assert got == [
        ("A|B", (0, 0), (1, 0), "x"), ("A|B", (0, 1), (1, 1), "x"),
        ("B|C", (1, 1), (2, 1), "x"), ("B|C", (2, 0), (2, 1), "y"),
    ]
    # Pair names are in the cells' area order of first appearance, independent of direction
    assert all(e["pair"] in ("A|B", "B|C") for e in edges)


def test_redraw_plan_frees_the_listed_frames_and_keeps_a_known_ring():
    from pixelphilly.projection import Frame
    from pixelphilly.regions import redraw_plan

    frames = [Frame(col=c, row=r, x0=c * 1024, y0=r * 1024, size=1024) for r in range(6) for c in range(6)]
    shared = {f.name: f.name for f in frames}  # the area's own drawing: every frame known
    run, known = redraw_plan(frames, shared, ["frame_02_02", "frame_03_02"], context=1)
    names = {f.name for f in run}
    # The two frames plus every frame within 1 of them: 4 x 3 = 12
    assert len(run) == 12 and {"frame_01_01", "frame_04_03"} <= names and "frame_05_02" not in names
    assert "frame_02_02" not in known and "frame_03_02" not in known
    assert set(known) == names - {"frame_02_02", "frame_03_02"}


def test_redraw_plan_refuses_unknown_frames():
    import pytest

    from pixelphilly.projection import Frame
    from pixelphilly.regions import redraw_plan

    frames = [Frame(col=0, row=0, x0=0, y0=0, size=1024)]
    with pytest.raises(ValueError):
        redraw_plan(frames, {}, ["frame_09_09"], context=1)
